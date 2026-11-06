import json
import re
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select

from lifereel_api.architecture.internal import call
from lifereel_api.architecture.topology import is_remote
from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing import service as billing
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.modules.script.constraints import merge_constraints, user_visual_constraints
from lifereel_api.modules.script.models import (
    ScriptGenerationReceipt,
    ScriptProject,
    ScriptScene,
    ScriptShot,
)
from lifereel_api.modules.script.schemas import (
    AdaptationBrief,
    AdaptationPlan,
    ScriptDialogue,
    ScriptShotUpdate,
    SequencePlan,
    SequencePlanItem,
    SourcedNote,
    StoryBible,
    StoryBibleEntry,
    StorySkeleton,
    StoryTimelineEntry,
    VisualConstraints,
)
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


class Dialogue(ScriptDialogue):
    @field_validator("kind", mode="before")
    @classmethod
    def normalize_narration_kind(cls, value):
        # These provider labels describe the same off-screen narration.
        if isinstance(value, str) and value.strip().casefold() in {
            "voiceover", "voice_over", "voice-over", "旁白",
        }:
            return "narration"
        return value


class Constraints(VisualConstraints):
    @field_validator("notes", mode="before")
    @classmethod
    def normalize_note_list(cls, value):
        # Some models express the same free-text notes as separate strings.
        if isinstance(value, list) and all(isinstance(note, str) for note in value):
            return "\n".join(value)
        return value


class Shot(ScriptShotUpdate):
    source_revision_ids: list[UUID] = Field(min_length=1, max_length=40)
    visual_constraints: Constraints = Field(default_factory=Constraints)
    action: str = Field(default="", max_length=1000)
    camera_intent: str = Field(default="", max_length=500)
    character_refs: list[str] = Field(default_factory=list, max_length=20)
    location_refs: list[str] = Field(default_factory=list, max_length=20)
    time_refs: list[str] = Field(default_factory=list, max_length=20)
    continuity_notes: list[str] = Field(default_factory=list, max_length=20)
    adaptation_metadata: dict = Field(default_factory=dict)


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence_key: str = Field(min_length=1, max_length=64)
    narrative_role: str = Field(min_length=1, max_length=100)
    character_refs: list[str] = Field(default_factory=list, max_length=20)
    location_refs: list[str] = Field(default_factory=list, max_length=20)
    time_refs: list[str] = Field(default_factory=list, max_length=20)
    continuity_notes: list[str] = Field(default_factory=list, max_length=20)
    heading: str = Field(min_length=1, max_length=180)
    plot: str = Field(min_length=1, max_length=4000)
    dialogues: list[Dialogue] = Field(min_length=1, max_length=40)
    story_skeleton: StorySkeleton
    visual_prompt: str = Field(min_length=1, max_length=4000)
    duration_seconds: int = Field(ge=4, strict=True)
    source_revision_ids: list[UUID] = Field(min_length=1, max_length=40)
    visual_constraints: Constraints = Field(default_factory=Constraints)
    shots: list[Shot] = Field(min_length=1)
    adaptation_metadata: dict = Field(default_factory=dict)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=180)
    scenes: list[Scene] = Field(min_length=1)


_NARRATIVE_ROLES = (
    "opening",
    "setup",
    "development",
    "turning_point",
    "aftermath",
    "closing",
    "transition",
    "montage",
)


def _known_revision_ids(snapshot: dict) -> list[UUID]:
    return [UUID(item["revision_id"]) for item in snapshot["revisions"]]


def _source_ids(raw: object, known: list[UUID]) -> list[UUID]:
    if raw is None:
        return list(known)
    if not isinstance(raw, list) or not raw:
        raise ValueError("invalid planning source references")
    values = []
    for value in raw:
        try:
            item = UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid planning source references") from exc
        if item not in known:
            raise ValueError("unknown planning source reference")
        if item not in values:
            values.append(item)
    return values


def _stable_key(value: object, fallback: str) -> str:
    key = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    return (key or fallback)[:64]


def _notes(raw: object, known: list[UUID]) -> list[SourcedNote]:
    if not isinstance(raw, list):
        return []
    output = []
    for item in raw[:20]:
        if isinstance(item, str) and item.strip():
            output.append(SourcedNote(text=item.strip()[:1000], source_revision_ids=known))
        elif isinstance(item, dict) and str(item.get("text", "")).strip():
            output.append(
                SourcedNote(
                    text=str(item["text"]).strip()[:1000],
                    source_revision_ids=_source_ids(item.get("source_revision_ids"), known),
                )
            )
    return output


def _bible_entries(raw: object, known: list[UUID]) -> list[StoryBibleEntry]:
    if not isinstance(raw, list):
        return []
    output = []
    for index, item in enumerate(raw[:80], 1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("title") or "").strip()
        if not name:
            continue
        entry_id = _stable_key(item.get("id"), f"entry-{index}")
        output.append(
            StoryBibleEntry(
                id=entry_id[:64],
                name=name[:180],
                notes=_notes(item.get("notes"), known),
                source_revision_ids=_source_ids(item.get("source_revision_ids"), known),
            )
        )
    return output


def _timeline_entries(raw: object, known: list[UUID]) -> list[StoryTimelineEntry]:
    if not isinstance(raw, list):
        return []
    output = []
    for index, item in enumerate(raw[:120], 1):
        if not isinstance(item, dict):
            continue
        event = str(item.get("event") or item.get("name") or "").strip()
        if not event:
            continue
        entry_id = _stable_key(item.get("id"), f"event-{index}")
        output.append(
            StoryTimelineEntry(
                id=entry_id[:64],
                event=event[:500],
                time_expression=(
                    str(item["time_expression"])[:180]
                    if item.get("time_expression") is not None
                    else None
                ),
                character_refs=[
                    str(value)[:64] for value in item.get("character_refs", [])
                    if isinstance(value, str)
                ][:20],
                location_ref=(
                    str(item["location_ref"])[:64]
                    if item.get("location_ref") is not None
                    else None
                ),
                source_revision_ids=_source_ids(item.get("source_revision_ids"), known),
            )
        )
    return output


def normalize_plan(snapshot: dict, raw: object, instructions: str, audience: str) -> AdaptationPlan:
    """Normalize legacy sketches and provider plans into source-bound artifacts."""
    known = _known_revision_ids(snapshot)
    data = raw if isinstance(raw, dict) else {}
    if all(key in data for key in ("adaptation_brief", "story_bible", "sequence_plan")):
        plan = AdaptationPlan.model_validate(data)
        if plan.adaptation_brief.intended_audience != audience:
            raise ValueError("planning audience mismatch")
        _validate_plan(plan, known)
        return plan
    brief_data = (
        data.get("adaptation_brief")
        if isinstance(data.get("adaptation_brief"), dict)
        else {}
    )
    brief = AdaptationBrief(
        theme=str(
            brief_data.get("theme") or data.get("theme") or snapshot["revisions"][0]["title"]
        ),
        intended_audience=audience,
        dramatic_question=(
            str(brief_data["dramatic_question"])[:1000]
            if brief_data.get("dramatic_question") is not None
            else None
        ),
        time_scope=(
            str(brief_data["time_scope"])[:500]
            if brief_data.get("time_scope") is not None
            else None
        ),
        must_include=_notes(
            brief_data.get("must_include") or data.get("must_include"),
            known,
        ),
        must_avoid=[
            str(value)[:500] for value in (
                brief_data.get("must_avoid") or data.get("must_avoid") or []
            )
            if isinstance(value, str)
        ][:40],
        tone=(
            str(brief_data["tone"])[:500]
            if brief_data.get("tone") is not None
            else instructions[:500] or None
        ),
        source_revision_ids=_source_ids(brief_data.get("source_revision_ids"), known),
    )
    bible_data = data.get("story_bible") if isinstance(data.get("story_bible"), dict) else {}
    bible = StoryBible(
        characters=_bible_entries(bible_data.get("characters"), known),
        locations=_bible_entries(bible_data.get("locations"), known),
        timeline=_timeline_entries(bible_data.get("timeline"), known),
        key_objects=_bible_entries(
            bible_data.get("key_objects") or bible_data.get("objects"),
            known,
        ),
        constraints=[
            str(value)[:500] for value in (
                bible_data.get("constraints") or []
            )
            if isinstance(value, str)
        ][:40],
        source_revision_ids=_source_ids(bible_data.get("source_revision_ids"), known),
    )
    sequence_data = data.get("sequence_plan")
    if isinstance(sequence_data, dict):
        sequence_data = sequence_data.get("items")
    if not isinstance(sequence_data, list):
        sequence_data = data.get("scene_plan")
    if not isinstance(sequence_data, list):
        sequence_data = []
    items = []
    for index, item in enumerate(sequence_data[:120], 1):
        if isinstance(item, str):
            title, summary = item[:180], item[:2000]
            item_data = {}
        elif isinstance(item, dict):
            item_data = item
            title = str(item.get("title") or item.get("heading") or f"场景 {index}")[:180]
            summary = str(item.get("summary") or item.get("plot") or title)[:2000]
        else:
            continue
        items.append(
            SequencePlanItem(
                key=_stable_key(item_data.get("key"), f"scene-{index}"),
                order_index=index,
                title=title,
                narrative_role=(
                    str(item_data.get("narrative_role"))
                    if item_data.get("narrative_role") in _NARRATIVE_ROLES
                    else (
                        "opening" if index == 1 else
                        "closing" if index == len(sequence_data) else
                        "development"
                    )
                ),
                summary=summary,
                source_revision_ids=_source_ids(
                    item_data.get("source_revision_ids"), known
                ),
                character_refs=[
                    str(value)[:64] for value in item_data.get("character_refs", [])
                    if isinstance(value, str)
                ][:20],
                location_refs=[
                    str(value)[:64] for value in item_data.get("location_refs", [])
                    if isinstance(value, str)
                ][:20],
            )
        )
    if not items:
        items = [
            SequencePlanItem(
                key=f"scene-{index}",
                order_index=index,
                title=revision["title"][:180],
                narrative_role=(
                    "opening" if index == 1 else
                    "closing" if index == len(snapshot["revisions"]) else
                    "development"
                ),
                summary=revision["body"][:2000],
                source_revision_ids=[UUID(revision["revision_id"])],
            )
            for index, revision in enumerate(snapshot["revisions"], 1)
        ]
    plan = AdaptationPlan(
        adaptation_brief=brief,
        story_bible=bible,
        sequence_plan=SequencePlan(items=items),
    )
    _validate_plan(plan, known)
    return plan


def _validate_plan(plan: AdaptationPlan, known: list[UUID]) -> None:
    known_set = set(known)
    brief = plan.adaptation_brief
    if not set(brief.source_revision_ids) <= known_set:
        raise ValueError("unknown adaptation brief source")
    for note in brief.must_include:
        if not set(note.source_revision_ids) <= known_set:
            raise ValueError("unknown adaptation note source")
    bible = plan.story_bible
    if not set(bible.source_revision_ids) <= known_set:
        raise ValueError("unknown story bible source")
    character_ids = [item.id for item in bible.characters]
    location_ids = [item.id for item in bible.locations]
    if len(character_ids) != len(set(character_ids)) or len(location_ids) != len(set(location_ids)):
        raise ValueError("duplicate story bible reference")
    for entry in [*bible.characters, *bible.locations, *bible.key_objects]:
        if not set(entry.source_revision_ids) <= known_set:
            raise ValueError("unknown story bible entry source")
        if any(not set(note.source_revision_ids) <= known_set for note in entry.notes):
            raise ValueError("unknown story bible note source")
    timeline_ids = [item.id for item in bible.timeline]
    if len(timeline_ids) != len(set(timeline_ids)):
        raise ValueError("duplicate timeline reference")
    for entry in bible.timeline:
        if not set(entry.source_revision_ids) <= known_set:
            raise ValueError("unknown timeline source")
        if any(ref not in character_ids for ref in entry.character_refs):
            raise ValueError("unknown timeline character")
        if entry.location_ref and entry.location_ref not in location_ids:
            raise ValueError("unknown timeline location")
    items = plan.sequence_plan.items
    keys = [item.key for item in items]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate sequence key")
    covered = set()
    for index, item in enumerate(items, 1):
        if item.order_index != index:
            raise ValueError("invalid sequence order")
        if not set(item.source_revision_ids) <= known_set:
            raise ValueError("unknown sequence source")
        covered.update(item.source_revision_ids)
        if any(ref not in character_ids for ref in item.character_refs):
            raise ValueError("unknown sequence character")
        if any(ref not in location_ids for ref in item.location_refs):
            raise ValueError("unknown sequence location")
    if covered != known_set:
        raise ValueError("incomplete sequence source coverage")


def _attach_plan_metadata(draft: Draft, plan: AdaptationPlan) -> Draft:
    items = {item.key: item for item in plan.sequence_plan.items}
    seen = set()
    for scene in draft.scenes:
        if not scene.sequence_key or scene.sequence_key not in items:
            raise ValueError("scene does not match sequence plan")
        if scene.sequence_key in seen:
            raise ValueError("duplicate scene sequence key")
        seen.add(scene.sequence_key)
        item = items[scene.sequence_key]
        if scene.narrative_role != item.narrative_role:
            raise ValueError("scene narrative role does not match sequence plan")
        if not set(scene.character_refs) <= set(item.character_refs):
            raise ValueError("unknown scene character reference")
        if not set(scene.location_refs) <= set(item.location_refs):
            raise ValueError("unknown scene location reference")
        scene.adaptation_metadata = {
            "sequence_key": scene.sequence_key,
            "narrative_role": scene.narrative_role,
            "character_refs": scene.character_refs or item.character_refs,
            "location_refs": scene.location_refs or item.location_refs,
            "time_refs": scene.time_refs,
            "continuity_notes": scene.continuity_notes,
        }
        for shot in scene.shots:
            if not set(shot.character_refs) <= set(item.character_refs):
                raise ValueError("unknown shot character reference")
            if not set(shot.location_refs) <= set(item.location_refs):
                raise ValueError("unknown shot location reference")
            shot.adaptation_metadata = {
                "action": shot.action,
                "camera_intent": shot.camera_intent,
                "character_refs": (
                    shot.character_refs or scene.character_refs or item.character_refs
                ),
                "location_refs": (
                    shot.location_refs or scene.location_refs or item.location_refs
                ),
                "time_refs": shot.time_refs or scene.time_refs,
                "continuity_notes": shot.continuity_notes or scene.continuity_notes,
            }
    if seen != set(items):
        raise ValueError("sequence plan contains unwritten scenes")
    if [scene.sequence_key for scene in draft.scenes] != [
        item.key for item in plan.sequence_plan.items
    ]:
        raise ValueError("scene order does not match sequence plan")
    return draft


def sources(db, tenant, subject_id, revision_ids=None, *, book_id=None):
    data = {"subject_id": str(subject_id), "revision_ids": list(map(str, revision_ids or []))}
    if book_id:
        data["book_id"] = str(book_id)
    if is_remote("book"):
        return call("book", "book.adaptation-sources", tenant, data)
    from lifereel_api.modules.book.adaptation import sources as local_sources

    return local_sources(db, tenant, data)


def validate(result, snapshot, duration=None, plan: AdaptationPlan | None = None):
    if plan and isinstance(result, dict) and isinstance(result.get("scenes"), list):
        result = {**result, "scenes": [dict(item) for item in result["scenes"]]}
        if len(result["scenes"]) == len(plan.sequence_plan.items):
            for scene, item in zip(
                result["scenes"], plan.sequence_plan.items, strict=True
            ):
                scene.setdefault("sequence_key", item.key)
                scene.setdefault("narrative_role", item.narrative_role)
    draft = Draft.model_validate(result)
    source_text = "\n".join(r["body"] for r in snapshot["revisions"])
    output_text = json.dumps(result, ensure_ascii=False)
    unsupported = set(re.findall(r"(?:19|20)\d{2}年", output_text)) - set(
        re.findall(r"(?:19|20)\d{2}年", source_text)
    )
    for label in ["中年女性", "中年男性", "年轻女性", "年轻男性", "女性主角", "男性主角"]:
        if label in output_text and label not in source_text:
            unsupported.add(label)
    if unsupported:
        raise ValueError("unsupported_factual_detail")
    known = {UUID(r["revision_id"]) for r in snapshot["revisions"]}
    used = set()
    for scene in draft.scenes:
        if not set(scene.source_revision_ids) <= known:
            raise ValueError("unknown_scene_source")
        used.update(scene.source_revision_ids)
        if plan:
            item = next(
                (
                    planned for planned in plan.sequence_plan.items
                    if planned.key == scene.sequence_key
                ),
                None,
            )
            if item is None or not set(scene.source_revision_ids) <= set(item.source_revision_ids):
                raise ValueError("scene source exceeds sequence plan")
        if sum(s.duration_seconds for s in scene.shots) != scene.duration_seconds:
            raise ValueError("incorrect_shot_duration")
        for shot in scene.shots:
            if not set(shot.source_revision_ids) <= set(scene.source_revision_ids):
                raise ValueError("unknown_shot_source")
    if (snapshot.get("book_id") or plan) and used != known:
        raise ValueError("missing_book_source")
    return draft


def mock_draft(snapshot, duration=None, planning: AdaptationPlan | None = None):
    if duration is None:
        scenes = []
        plan_index = 0
        for revision in snapshot["revisions"]:
            for offset in range(0, len(revision["body"]), 1200):
                item = (
                    planning.sequence_plan.items[plan_index]
                    if planning and plan_index < len(planning.sequence_plan.items)
                    else None
                )
                plan_index += 1
                text = revision["body"][offset:offset + 1200]
                seconds = max(4, (len(text) + 3) // 4)
                scenes.append({
                    "sequence_key": item.key if item else f"scene-{plan_index}",
                    "narrative_role": (
                        item.narrative_role
                        if item
                        else (
                            "opening" if plan_index == 1 else
                            "closing" if offset + 1200 >= len(revision["body"])
                            and revision is snapshot["revisions"][-1] else
                            "development"
                        )
                    ),
                    "character_refs": item.character_refs if item else [],
                    "location_refs": item.location_refs if item else [],
                    "heading": revision["title"], "plot": text,
                    "dialogues": [{"kind": "narration", "speaker": "讲述者", "text": text}],
                    "story_skeleton": {
                        "opening": text[:40], "beats": [text[:600]], "ending": text[-40:],
                    },
                    "visual_prompt": text, "duration_seconds": seconds,
                    "source_revision_ids": [revision["revision_id"]],
                    "shots": [{
                        "shot_type": "wide", "visual_prompt": text,
                        "duration_seconds": seconds,
                        "source_revision_ids": [revision["revision_id"]],
                        "character_refs": item.character_refs if item else [],
                        "location_refs": item.location_refs if item else [],
                    }],
                })
        return {"title": snapshot.get("title", snapshot["revisions"][0]["title"]), "scenes": scenes}
    revision = snapshot["revisions"][0]
    source_id = revision["revision_id"]
    text = revision["body"][:150]
    scenes = []
    for index, seconds in enumerate([duration // 2, duration - duration // 2], 1):
        count = (seconds + 9) // 10
        base, remainder = divmod(seconds, count)
        shots = [
            {
                "shot_type": "wide",
                "visual_prompt": text,
                "duration_seconds": base + (1 if i < remainder else 0),
                "source_revision_ids": [source_id],
                "visual_constraints": {},
            }
            for i in range(count)
        ]
        scenes.append(
            {
                "sequence_key": f"scene-{index}",
                "narrative_role": "opening" if index == 1 else "closing",
                "character_refs": [],
                "location_refs": [],
                "heading": f"{revision['title']} · 场景{index}",
                "plot": text,
                "dialogues": [{"kind": "narration", "speaker": "讲述者", "text": text}],
                "story_skeleton": {"opening": text[:40], "beats": [text], "ending": text[-40:]},
                "visual_prompt": text,
                "duration_seconds": seconds,
                "source_revision_ids": [source_id],
                "visual_constraints": {},
                "shots": shots,
            }
        )
    return {"title": revision["title"] + " · 测试改编", "scenes": scenes}


def mock_plan(snapshot: dict, instructions: str, audience: str) -> AdaptationPlan:
    revisions = snapshot["revisions"]
    ids = [UUID(item["revision_id"]) for item in revisions]
    plan_items = []
    for revision in revisions:
        revision_id = UUID(revision["revision_id"])
        for offset in range(0, len(revision["body"]), 1200):
            index = len(plan_items) + 1
            plan_items.append(
                SequencePlanItem(
                    key=f"scene-{index}",
                    order_index=index,
                    title=revision["title"][:180],
                    narrative_role=(
                        "opening" if index == 1 else
                        "closing" if offset + 1200 >= len(revision["body"])
                        and revision is revisions[-1] else
                        "development"
                    ),
                    summary=revision["body"][offset:offset + 2000],
                    source_revision_ids=[revision_id],
                )
            )
    return AdaptationPlan(
        adaptation_brief=AdaptationBrief(
            theme="基于已保存书稿的人生纪实",
            intended_audience=audience,
            must_include=[
                SourcedNote(
                    text=f"保留《{revision['title']}》中的主要已记录经历",
                    source_revision_ids=[UUID(revision["revision_id"])],
                )
                for revision in revisions
            ],
            must_avoid=[instructions] if instructions else [],
            tone="纪实、克制，不补写来源中没有的事实",
            source_revision_ids=ids,
        ),
        story_bible=StoryBible(source_revision_ids=ids),
        sequence_plan=SequencePlan(items=plan_items),
    )


def generate(db, tenant, payload):
    from lifereel_api.modules.book.service import digest
    from lifereel_api.modules.script.service import get_project

    request_id = payload.idempotency_key or uuid4()
    request_data = payload.model_dump(mode="json")
    if not payload.book_id:
        request_data.pop("book_id")
    fingerprint = digest(request_data)
    key = f"book-script:{request_id}"
    with execution_lock(db, payload.subject_id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.BILLING_BUSY)
        receipt = db.get(ScriptGenerationReceipt, (tenant, request_id))
        if receipt:
            if receipt.fingerprint != fingerprint:
                raise ApiError(409, ErrorCode.PROFILE_REQUEST_CONFLICT)
            if receipt.project_id:
                return get_project(db, tenant, receipt.project_id)
            if receipt.status.endswith("_inflight"):
                raise ApiError(409, ErrorCode.BILLING_USAGE_PENDING)
        snapshot = sources(
            db, tenant, payload.subject_id, payload.book_revision_ids, book_id=payload.book_id,
        )
        if receipt and receipt.checkpoint.get("source_digest") != digest(snapshot):
            raise ApiError(409, ErrorCode.BOOK_SOURCE_CHANGED)
        if not receipt:
            receipt = ScriptGenerationReceipt(
                tenant_id=tenant,
                request_id=request_id,
                fingerprint=fingerprint,
                project_id=None,
                status="prepared",
                checkpoint={"source_digest": digest(snapshot), "snapshot": snapshot},
            )
            db.add(receipt)
            db.commit()
        settings = get_settings()
        billing.reserve(
            db,
            tenant,
            key,
            billing.script_update_price(),
            "script",
            "书稿改编剧本",
            {**billing.prices(), "request_fingerprint": fingerprint},
        )
        db.commit()
        try:
            result = receipt.checkpoint.get("draft")
            planning = normalize_plan(
                snapshot,
                receipt.checkpoint.get("planning") or receipt.checkpoint.get("sketch"),
                payload.adaptation_instructions,
                payload.audience,
            )
            if result is None:
                client = OpenAICompatibleClient(
                    settings.openai_compatible_base_url or "",
                    settings.openai_compatible_api_key or "",
                    settings.model_for("script"),
                    task="script",
                )
                if settings.llm_provider != "mock" and not client.capabilities().configured:
                    raise ApiError(503, ErrorCode.SCRIPT_LLM_CONFIGURATION_INCOMPLETE)
                sketch = receipt.checkpoint.get("sketch")
                if sketch is None:
                    receipt.status = "sketch_inflight"
                    db.commit()
                    sketch = (
                        mock_plan(
                            snapshot,
                            payload.adaptation_instructions,
                            payload.audience,
                        ).model_dump(mode="json")
                        if settings.llm_provider == "mock"
                        else client.chat_json(
                            "你负责整本纪实书稿的影视改编规划。先理解给定书稿，"
                            "再输出可审阅的adaptation_brief、story_bible和sequence_plan。"
                            "规划主题、人物、地点、时间线、关键物件、场景顺序和叙事作用，"
                            "覆盖各章的主要经历和转折。只改编给定正文，不虚构年份、性别、"
                            "真实对白或经历。所有人物、地点、时间线、物件和场景必须引用输入"
                            "revision_id；没有证据的字段留空，不凭空补齐。"
                            "adaptation_brief.must_include使用{text,source_revision_ids}，"
                            "story_bible中的characters、locations、key_objects使用"
                            "{id,name,notes,source_revision_ids}，timeline使用"
                            "{id,event,time_expression,character_refs,location_ref,source_revision_ids}，"
                            "sequence_plan.items使用{key,title,narrative_role,summary,"
                            "source_revision_ids,character_refs,location_refs}。"
                            "narrative_role只能是opening、setup、development、turning_point、"
                            "aftermath、closing、transition或montage。返回严格JSON。",
                            json.dumps(
                                {
                                    "source": snapshot,
                                    "instructions": payload.adaptation_instructions,
                                    "audience": payload.audience,
                                    "output_schema": AdaptationPlan.model_json_schema(),
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )
                    planning = normalize_plan(
                        snapshot,
                        sketch,
                        payload.adaptation_instructions,
                        payload.audience,
                    )
                    sketch = planning.model_dump(mode="json")
                    receipt.checkpoint = {
                        **receipt.checkpoint,
                        "sketch": sketch,
                        "planning": sketch,
                    }
                    receipt.status = "sketch_ready"
                    db.commit()
                receipt.status = "draft_inflight"
                db.commit()
                result = (
                    mock_draft(snapshot, None)
                    if settings.llm_provider == "mock"
                    else client.chat_json(
                        "按整本书稿和规划生成完整纪实影视剧本JSON，按目录顺序覆盖全部成稿章节的"
                        "主要经历和转折。严格按sequence_plan逐项生成恰好一个scene，顺序和sequence_key"
                        "必须完全一致；不得新增、漏写或合并plan item。场景按叙事需要安排，"
                        "不按原章节机械分割，也不限制总时长。"
                        "不得补造性别、年龄、事实或真实引语。"
                        "返回title,scenes。每场含sequence_key,narrative_role,character_refs,location_refs,"
                        "time_refs,continuity_notes,heading,plot,dialogues(kind/speaker/text),"
                        "story_skeleton(opening/beats/turning_point/ending),visual_prompt,duration_seconds,"
                        "source_revision_ids,visual_constraints(face_policy/required_elements/forbidden_elements/notes),"
                        "shots。每镜头含shot_type(wide/medium/closeup/detail/archive),action,camera_intent,"
                        "character_refs,location_refs,time_refs,continuity_notes,visual_prompt,"
                        "duration_seconds,source_revision_ids,visual_constraints。"
                        "dialogues.kind只能为narration或dialogue，旁白使用narration。"
                        "字段及类型遵循output_schema；visual_constraints.notes是字符串或null，"
                        "required_elements和forbidden_elements才是字符串数组。"
                        "引用只能来自输入revision_id，每场引用覆盖其镜头引用。"
                        "每场和每镜头的时长是依据旁白、对白与动作节奏给出的正整数秒预估，"
                        "各场镜头时长之和等于场时长。不要为凑固定时长省略经历或加快语速。"
                        "要求不露脸时逐镜头继承no_identifiable_faces。同一人物保持稳定标识与形象。",
                        json.dumps(
                            {
                                "source": snapshot,
                                "planning": planning.model_dump(mode="json"),
                                "instructions": payload.adaptation_instructions,
                                "output_schema": Draft.model_json_schema(),
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
                draft = _attach_plan_metadata(validate(result, snapshot, plan=planning), planning)
                receipt.checkpoint = {
                    **receipt.checkpoint,
                    "draft": draft.model_dump(mode="json"),
                    "planning": planning.model_dump(mode="json"),
                }
                receipt.status = "draft_ready"
                db.commit()
            else:
                draft = _attach_plan_metadata(validate(result, snapshot, plan=planning), planning)
            if digest(sources(
                db, tenant, payload.subject_id, payload.book_revision_ids, book_id=payload.book_id,
            )) != digest(snapshot):
                raise ApiError(409, ErrorCode.BOOK_SOURCE_CHANGED)
            old = list(
                db.scalars(
                    select(ScriptProject).where(
                        ScriptProject.tenant_id == tenant,
                        ScriptProject.subject_id == payload.subject_id,
                        ScriptProject.status != "superseded",
                    )
                )
            )
            for project in old:
                project.status = "superseded"
            db.flush()
            project = ScriptProject(
                tenant_id=tenant,
                subject_id=payload.subject_id,
                title=draft.title,
                mode="multi_chapter",
                audience=payload.audience,
                status="draft",
                source_type="book",
                source_snapshot=snapshot,
                adaptation_brief=planning.adaptation_brief.model_dump(mode="json"),
                story_bible=planning.story_bible.model_dump(mode="json"),
                sequence_plan=planning.sequence_plan.model_dump(mode="json"),
                source_claim_ids=[r["revision_id"] for r in snapshot["revisions"]],
                generation_provider=settings.llm_provider,
                generation_model=settings.model_for("script"),
            )
            db.add(project)
            db.flush()
            preference_text = "\n".join(
                str(e["value"])
                for r in snapshot["revisions"]
                for e in r.get("preferences", [])
                if e["field_key"] == "preferences.visual_constraints"
            )
            required = user_visual_constraints(payload.adaptation_instructions, preference_text)
            for index, scene in enumerate(draft.scenes, 1):
                scene_row = ScriptScene(
                    tenant_id=tenant,
                    project_id=project.id,
                    chapter_id=None,
                    order_index=index,
                    heading=scene.heading,
                    plot=scene.plot,
                    dialogues=[d.model_dump() for d in scene.dialogues],
                    narration="\n".join(d.text for d in scene.dialogues),
                    visual_prompt=scene.visual_prompt,
                    duration_seconds=scene.duration_seconds,
                    source_claim_ids=list(map(str, scene.source_revision_ids)),
                    story_skeleton=scene.story_skeleton.model_dump(),
                    adaptation_metadata=scene.adaptation_metadata,
                    visual_constraints=merge_constraints(
                        scene.visual_constraints.model_dump(), required
                    ),
                )
                db.add(scene_row)
                db.flush()
                for shot_index, shot in enumerate(scene.shots, 1):
                    db.add(
                        ScriptShot(
                            tenant_id=tenant,
                            scene_id=scene_row.id,
                            order_index=shot_index,
                            shot_type=shot.shot_type,
                            visual_prompt=shot.visual_prompt,
                            duration_seconds=shot.duration_seconds,
                            source_claim_ids=list(map(str, shot.source_revision_ids)),
                            adaptation_metadata=shot.adaptation_metadata,
                            visual_constraints=merge_constraints(
                                scene_row.visual_constraints, shot.visual_constraints.model_dump()
                            ),
                        )
                    )
            receipt.project_id, receipt.status = project.id, "completed"
            from lifereel_api.modules.book.service import transition

            transition(db, tenant, key, True)
            db.commit()
            return get_project(db, tenant, project.id)
        except (ValidationError, ValueError):
            db.rollback()
            receipt.status = "failed"
            from lifereel_api.modules.book.service import transition

            transition(db, tenant, key, False)
            db.commit()
            raise ApiError(502, ErrorCode.SCRIPT_LLM_RESPONSE_INVALID) from None
        except Exception as exc:
            db.rollback()
            if not isinstance(exc, ApiError) or exc.code != ErrorCode.MODEL_INVOCATION_UNCERTAIN:
                receipt.status = "failed"
            from lifereel_api.modules.book.service import transition

            transition(db, tenant, key, False)
            db.commit()
            raise

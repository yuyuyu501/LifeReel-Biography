from __future__ import annotations

import hashlib
import json
import logging
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.processing_limits import get_processing_limits, require_budget
from lifereel_api.modules.billing import service as billing
from lifereel_api.modules.billing.models import Charge
from lifereel_api.modules.billing.usage import track_usage
from lifereel_api.modules.identity.models import Person
from lifereel_api.modules.interview.chapter_prompts import (
    ChapterPromptProfile,
    get_chapter_prompt_profile,
)
from lifereel_api.modules.interview.models import Chapter, InterviewSession, InterviewTurnWorkflow
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.modules.script.models import ScriptProject, ScriptScene, ScriptShot
from lifereel_api.modules.script.schemas import (
    ScriptDialogue,
    ScriptGenerateRequest,
    ScriptSceneUpdate,
    ScriptShotUpdate,
)
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

logger = logging.getLogger(__name__)


def _script_input(request: dict) -> str:
    """Bound the complete serialized request, including the current user-edited script."""
    limit = get_processing_limits().script_input_max_chars

    def check_strings(value):
        if isinstance(value, str):
            # JSONEncoder emits each string as one piece. Check before escaping
            # so a legacy 50 MiB field never needs a second full-size allocation.
            require_budget(
                len(value), limit, stage="script_input", code=ErrorCode.SCRIPT_INPUT_TOO_LARGE,
            )
        elif isinstance(value, dict):
            for key, item in value.items():
                check_strings(key)
                check_strings(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                check_strings(item)

    check_strings(request)
    pieces = []
    size = 0
    for piece in json.JSONEncoder(ensure_ascii=False).iterencode(request):
        size += len(piece)
        require_budget(size, limit, stage="script_input", code=ErrorCode.SCRIPT_INPUT_TOO_LARGE)
        pieces.append(piece)
    return "".join(pieces)


def _validate_generated_scene(scene: dict, allowed_ids: set[str]) -> dict:
    """Validate both providers against the editable/output contract before any DB mutation."""
    try:
        edited = ScriptSceneUpdate.model_validate({
            "expected_version": 1,
            **{key: scene[key] for key in (
                "heading", "plot", "dialogues", "visual_prompt", "duration_seconds",
            )},
            "shots": [{key: shot[key] for key in (
                "shot_type", "visual_prompt", "duration_seconds",
            )} for shot in scene["shots"]],
        })
        if not edited.plot or not edited.shots or not 15 <= edited.duration_seconds <= 30:
            raise ValueError("invalid generated chapter")
        if sum(shot.duration_seconds for shot in edited.shots) != edited.duration_seconds:
            raise ValueError("shot durations do not match chapter")
        if any(not line.text.strip() or not line.speaker.strip() for line in edited.dialogues):
            raise ValueError("empty spoken line")
        for item in [scene, *scene["shots"]]:
            references = item["source_claim_ids"]
            if (not isinstance(references, list) or not references
                    or any(not isinstance(ref, str) or ref not in allowed_ids
                           for ref in references)):
                raise ValueError("invalid evidence references")
        canonical = "\n".join(line.text for line in edited.dialogues)
        if scene["narration"] != canonical:
            raise ValueError("narration does not match dialogues")
        normalized = edited.model_dump(exclude={"expected_version", "shots"})
        return {**scene, **normalized, "narration": canonical, "shots": [
            {**original, **shot.model_dump()}
            for original, shot in zip(scene["shots"], edited.shots, strict=True)
        ]}
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError(502, ErrorCode.SCRIPT_LLM_RESPONSE_INVALID) from exc


def _fit_shot_durations(shots: list[dict], scene_duration: int) -> list[dict]:
    if not shots:
        return shots
    shots = shots[: max(1, scene_duration // 2)]
    base_seconds = 2
    remaining = scene_duration - base_seconds * len(shots)
    weights = [max(1, int(shot["duration_seconds"])) for shot in shots]
    total_weight = sum(weights)
    extras = [(remaining * weight) // total_weight for weight in weights]
    for index in range(remaining - sum(extras)):
        extras[index % len(extras)] += 1
    return [
        {**shot, "duration_seconds": base_seconds + extras[index]}
        for index, shot in enumerate(shots)
    ]


def _rule_scenes(
    subject_name: str,
    claims: list[MemoryClaim],
    profile: ChapterPromptProfile | None = None,
) -> list[dict]:
    source_ids = [str(claim.id) for claim in claims]
    chapter_title = profile["title"] if profile else "岁月片段"
    introduction = f"我是{subject_name}。" if chapter_title == "我是谁" else ""
    # Mock generation cannot summarize faithfully. Reject an oversized verbatim
    # draft instead of truncating evidence or persisting an unreadable workspace.
    spoken_size = len(introduction) + max(0, len(claims) - 1) * 2
    for claim in claims:
        spoken_size += len(claim.claim_text.rstrip("。")) + 1
        require_budget(
            spoken_size, 2000, stage="script_mock_output",
            code=ErrorCode.SCRIPT_MOCK_OUTPUT_TOO_LARGE,
        )
    memories = "\n\n".join(claim.claim_text.rstrip("。") + "。" for claim in claims)
    visual_prompt = (
        f"围绕“{chapter_title}”的纪实电影画面，符合人物年代与地域；"
        "只呈现来源记忆中已有的细节，不得擅自生成未经授权的真实人脸。"
    )
    duration = max(15, min(30, (len(introduction + memories) + 3) // 4))
    scenes = [
        {
            "heading": chapter_title,
            "plot": memories,
            "dialogues": [{"kind": "narration", "speaker": subject_name,
                           "text": f"{introduction}{memories}"}],
            "narration": f"{introduction}{memories}",
            "visual_prompt": visual_prompt,
            "duration_seconds": duration,
            "source_claim_ids": source_ids,
            "shots": [
                {
                    "shot_type": "wide",
                    "visual_prompt": f"本章环境建立镜头。{visual_prompt}",
                    "duration_seconds": duration // 2,
                    "source_claim_ids": source_ids,
                },
                {
                    "shot_type": "detail",
                    "visual_prompt": f"本章关键生活细节特写。{visual_prompt}",
                    "duration_seconds": duration - duration // 2,
                    "source_claim_ids": source_ids,
                },
            ],
        }
    ]
    return [_validate_generated_scene(scene, set(source_ids)) for scene in scenes]


def _llm_scenes(
    subject: Person,
    payload: ScriptGenerateRequest,
    claims: list[MemoryClaim],
    profile: ChapterPromptProfile,
    update_brief: dict | None = None,
) -> tuple[str | None, list[dict], str]:
    settings = get_settings()
    model = settings.model_for("script")
    client = OpenAICompatibleClient(
        settings.openai_compatible_base_url or "",
        settings.openai_compatible_api_key or "",
        model,
    )
    if not client.capabilities().configured:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.SCRIPT_LLM_CONFIGURATION_INCOMPLETE,
        )
    evidence_pack = [
        {
            "claim_id": str(claim.id),
            "claim_text": claim.claim_text,
            "source_quote": claim.source_quote,
            "confidence": claim.confidence,
            "review_status": claim.review_status,
        }
        for claim in claims
    ]
    request = {
        "subject": {
            "name": subject.preferred_name or subject.display_name,
        },
        "mode": payload.mode,
        "audience": payload.audience,
        "requested_title": payload.title,
        "chapter_profile": profile,
        "evidence_pack": evidence_pack,
        "update_brief": update_brief,
        "duration_range_seconds": {"min": 15, "max": 30},
    }
    serialized_request = _script_input(request)
    try:
        result = client.chat_json(
            f"你是中文口述史短视频编剧。当前只能写“{profile['title']}”这一章，"
            f"写作目标是：{profile['script_goal']}。只使用 evidence_pack 中与 chapter_profile"
            "相关的信息，不得引入其他生命章节，不得补写未提供的事实。每次调用都要把全部"
            "证据融合为一份完整、连续的当前章节稿件，而不是新增草稿、场景或片段列表。"
            "使用第一人称、自然口语和克制情感；新信息应融入原有叙事并改善连贯性。"
            "update_brief.current_script是当前稿件，可能包含用户手动修改，应保留其表达偏好；"
            "update_brief.script_instructions是用户本次重写要求，只用于调整叙事、分镜、台词或场景，"
            "不得当作人物生平事实，不得越过本章主题或证据边界。仍须完整返回四部分。"
            "本章短视频总时长必须在15至30秒之间，根据最终旁白实际字数、自然停顿和"
            "画面节奏选择整数秒，不要每次都写30秒。口述旁白约每秒3至4个汉字，"
            "为停顿和转场留出时间；信息较少可用15至20秒，较丰富用21至30秒。"
            "如全部信息无法在30秒内自然讲完，请保留本章核心事实、精炼旁白，"
            "不要靠加速朗读或超过30秒塞入内容。各镜头时长之和应等于本章总时长。"
            "chapter.source_claim_ids 和每个镜头的 source_claim_ids 必须填写实际支撑内容的"
            "claim_id，且只能引用输入中的 claim_id。未核对信息保留不确定语气。"
            "剧本分为四部分：plot是简洁的剧情概述（事情如何发生和发展，不是旁白复写）；"
            "shots是含景别、动作、运镜与时长的分镜；dialogues是按播放顺序排列的所有口播；"
            "visual_prompt是整体场景描述，说明有据可查的年代、地点、环境、人物外观与氛围。"
            "dialogues每项包含kind（narration或dialogue）、speaker、text。"
            "旁白用narration标记，人物原话只有证据中确实提供时才使用dialogue，禁止编造对话。"
            "只有旁白也必须用dialogues列表表达。不输出独立narration，程序会从dialogues顺序拼接。"
            "对话和旁白的总朗读时长必须计入章节时长，不得把说明文字写入口播。"
            "输出严格 JSON，以下结构中的22秒仅为格式示例，实际时长须独立估算："
            '{"title":"整本书名（可选）","chapter":{"heading":"本章标题",'
            '"plot":"本章剧情概述",'
            '"dialogues":[{"kind":"narration","speaker":"主人公","text":"本章旁白"}],'
            '"visual_prompt":"本章场景描述",'
            '"duration_seconds":22,"source_claim_ids":["..."],'
            '"shots":[{"shot_type":"wide|medium|closeup|detail|archive",'
            '"visual_prompt":"...","duration_seconds":6,"source_claim_ids":["..."]}]}}。',
            serialized_request,
        )
    except json.JSONDecodeError as exc:
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.SCRIPT_LLM_RESPONSE_INVALID,
        ) from exc
    except ApiError:
        raise
    except Exception as exc:
        logger.warning("Script generation provider request failed: error_type=%s",
                       type(exc).__name__)
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.SCRIPT_LLM_REQUEST_FAILED,
        ) from exc

    allowed_ids = {str(claim.id) for claim in claims}
    raw_chapter = result.get("chapter") if isinstance(result, dict) else None
    if not isinstance(raw_chapter, dict):
        logger.warning(
            "Invalid script model response: chapter_type=%s response_key_count=%s",
            type(raw_chapter).__name__,
            len(result) if isinstance(result, dict) else 0,
        )
        raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.SCRIPT_LLM_RESPONSE_INVALID)
    try:
        raw_source_ids = raw_chapter["source_claim_ids"]
        if (not isinstance(raw_source_ids, list) or not raw_source_ids
                or any(not isinstance(value, str) for value in raw_source_ids)):
            raise ValueError("chapter has no valid evidence references")
        source_ids = list(dict.fromkeys(value for value in raw_source_ids if value in allowed_ids))
        if not source_ids:
            raise ValueError("chapter has no valid evidence references")
        duration = raw_chapter["duration_seconds"]
        if type(duration) is not int or not 15 <= duration <= 30:
            raise ValueError("chapter duration must be an integer between 15 and 30")
        shots = []
        raw_shots = raw_chapter.get("shots")
        if not isinstance(raw_shots, list) or not 1 <= len(raw_shots) <= min(12, duration // 2):
            raise ValueError("invalid chapter shots")
        for raw_shot in raw_shots:
            if not isinstance(raw_shot, dict):
                raise ValueError("shot is not an object")
            raw_shot_source_ids = raw_shot["source_claim_ids"]
            if (not isinstance(raw_shot_source_ids, list) or not raw_shot_source_ids
                    or any(not isinstance(value, str) for value in raw_shot_source_ids)):
                raise ValueError("shot has no valid evidence or visual prompt")
            shot_source_ids = list(dict.fromkeys(
                value for value in raw_shot_source_ids if value in allowed_ids
            ))
            if not shot_source_ids:
                raise ValueError("shot has no valid evidence or visual prompt")
            validated_shot = ScriptShotUpdate.model_validate({
                "shot_type": raw_shot.get("shot_type", "medium"),
                "visual_prompt": raw_shot["visual_prompt"],
                "duration_seconds": raw_shot.get("duration_seconds", 6),
            })
            source_ids.extend(
                claim_id for claim_id in shot_source_ids if claim_id not in source_ids
            )
            shots.append(
                {
                    **validated_shot.model_dump(),
                    "source_claim_ids": shot_source_ids,
                }
            )
        if not shots:
            raise ValueError("chapter has no generated shots")
        shots = _fit_shot_durations(shots, duration)
        heading = raw_chapter.get("heading", profile["title"])
        plot = raw_chapter["plot"]
        if not isinstance(plot, str) or not plot.strip() or len(plot) > 4000:
            raise ValueError("invalid chapter plot")
        raw_dialogues = raw_chapter["dialogues"]
        if not isinstance(raw_dialogues, list) or not 1 <= len(raw_dialogues) <= 40:
            raise ValueError("invalid chapter dialogues")
        dialogues = [ScriptDialogue.model_validate(line).model_dump() for line in raw_dialogues]
        if any(not line["text"].strip() or not line["speaker"].strip() for line in dialogues):
            raise ValueError("empty spoken line")
        narration = "\n".join(line["text"] for line in dialogues)
        visual_prompt = raw_chapter["visual_prompt"]
        if not heading or not narration or not visual_prompt:
            raise ValueError("chapter text is empty")
        scene = {
            "heading": heading,
            "plot": plot.strip(),
            "dialogues": dialogues,
            "narration": narration,
            "visual_prompt": visual_prompt,
            "duration_seconds": duration,
            "source_claim_ids": source_ids,
            "shots": shots,
        }
        scene = _validate_generated_scene(scene, allowed_ids)
        title = result.get("title")
        if title is not None and (not isinstance(title, str) or len(title) > 180):
            raise ValueError("invalid project title")
    except (KeyError, TypeError, ValueError, StopIteration) as exc:
        logger.warning(
            "Invalid script model response: error_type=%s allowed_claim_count=%s",
            type(exc).__name__,
            len(allowed_ids),
        )
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.SCRIPT_LLM_RESPONSE_INVALID,
        ) from exc
    return (title or "").strip() or None, [scene], model


def list_projects(db: Session, tenant_id: UUID) -> list[ScriptProject]:
    return list(
        db.scalars(
            select(ScriptProject)
            .where(
                ScriptProject.tenant_id == tenant_id,
                ScriptProject.status != "superseded",
            )
            .order_by(ScriptProject.created_at.desc())
        )
    )


def get_project(
    db: Session, tenant_id: UUID, project_id: UUID
) -> tuple[ScriptProject, list[ScriptScene], list[ScriptShot]]:
    project = db.scalar(
        select(ScriptProject).where(
            ScriptProject.id == project_id, ScriptProject.tenant_id == tenant_id
        )
    )
    if project is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.SCRIPT_PROJECT_NOT_FOUND)
    scenes = list(
        db.scalars(
            select(ScriptScene)
            .where(ScriptScene.project_id == project.id, ScriptScene.tenant_id == tenant_id)
            .order_by(ScriptScene.order_index)
        )
    )
    scene_ids = [item.id for item in scenes]
    shots = (
        list(
            db.scalars(
                select(ScriptShot)
                .where(ScriptShot.scene_id.in_(scene_ids))
                .order_by(ScriptShot.scene_id, ScriptShot.order_index)
            )
        )
        if scene_ids
        else []
    )
    return project, scenes, shots


def update_fingerprint(payload: ScriptGenerateRequest) -> str:
    return hashlib.sha256(
        json.dumps(
            payload.model_dump(mode="json", exclude={"idempotency_key"}), sort_keys=True
        ).encode()
    ).hexdigest()


def reserve_interview_update(db: Session, tenant_id: UUID, payload: ScriptGenerateRequest) -> str:
    # Use the script's charge identity so preprocessing and generation share one reservation.
    if payload.idempotency_key is None or payload.mode != "single_chapter":
        raise ApiError(409, ErrorCode.BILLING_STATE_INVALID)
    person = db.scalar(
        select(Person).where(Person.id == payload.subject_id, Person.tenant_id == tenant_id)
    )
    if person is None:
        raise ApiError(404, ErrorCode.SUBJECT_NOT_FOUND)
    chapter = db.get(Chapter, payload.chapter_id) if payload.chapter_id else None
    key = f"script-update:{payload.idempotency_key}:{payload.chapter_id or 'free'}"
    charge = billing.reserve(
        db,
        tenant_id,
        key,
        billing.script_update_price(),
        "script",
        f"{person.preferred_name or person.display_name} · "
        f"{chapter.title if chapter else '自由采访'}",
        {**billing.prices(), "request_fingerprint": update_fingerprint(payload)},
    )
    if charge.price_snapshot.get("request_fingerprint") != update_fingerprint(payload):
        raise ApiError(409, ErrorCode.BILLING_STATE_INVALID)
    return key


@track_usage("script")
def generate_draft(
    db: Session, tenant_id: UUID, payload: ScriptGenerateRequest, update_brief: dict | None = None
):
    # One update can be retried, but a new update of the same chapter is a new charge.
    with execution_lock(db, payload.subject_id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.BILLING_BUSY)
        person = db.scalar(
            select(Person).where(Person.id == payload.subject_id, Person.tenant_id == tenant_id)
        )
        if person is None:
            raise ApiError(404, ErrorCode.SUBJECT_NOT_FOUND)
        request_id = payload.idempotency_key or uuid4()
        prefix = f"script-update:{request_id}:"
        fingerprint = update_fingerprint(payload)
        billing.lock_wallet(db, tenant_id)
        previous = list(
            db.scalars(
                select(Charge).where(
                    Charge.tenant_id == tenant_id,
                    Charge.kind == "script",
                    Charge.business_key.startswith(prefix),
                )
            )
        )
        if any(item.price_snapshot.get("request_fingerprint") != fingerprint for item in previous):
            raise ApiError(409, ErrorCode.BILLING_STATE_INVALID)
        if previous and all(item.status == "settled" for item in previous):
            result = get_project(
                db, tenant_id, UUID(previous[0].price_snapshot["result_project_id"])
            )
            db.commit()
            return result
        statement = select(MemoryClaim.chapter_id).where(
            MemoryClaim.tenant_id == tenant_id,
            MemoryClaim.subject_id == person.id,
            MemoryClaim.review_status.not_in(["disputed", "private"]),
        )
        if payload.chapter_id:
            statement = statement.where(MemoryClaim.chapter_id == payload.chapter_id)
        chapter_ids = list(dict.fromkeys(db.scalars(statement)))
        if not chapter_ids:
            raise ApiError(409, ErrorCode.SCRIPT_MEMORIES_REQUIRED)
        if payload.mode != "multi_chapter" or payload.chapter_id:
            chapter_ids = [payload.chapter_id]
        if previous and {item.business_key for item in previous} != {
            f"{prefix}{chapter_id or 'free'}" for chapter_id in chapter_ids
        }:
            raise ApiError(409, ErrorCode.BILLING_STATE_INVALID)
        keys = []
        try:
            for chapter_id in chapter_ids:
                key = f"{prefix}{chapter_id or 'free'}"
                chapter = db.get(Chapter, chapter_id) if chapter_id else None
                billing.reserve(
                    db,
                    tenant_id,
                    key,
                    billing.script_update_price(),
                    "script",
                    f"{person.preferred_name or person.display_name} · "
                    f"{chapter.title if chapter else '自由采访'}",
                    {**billing.prices(), "request_fingerprint": fingerprint},
                )
                keys.append(key)
            db.commit()
            return _generate_draft(db, tenant_id, payload, update_brief, billing_keys=keys)
        except Exception:
            db.rollback()
            for key in keys:
                billing.transition(db, tenant_id, key, False)
            db.commit()
            raise


def _generate_draft(
    db: Session,
    tenant_id: UUID,
    payload: ScriptGenerateRequest,
    update_brief: dict | None = None,
    billing_keys: list[str] | None = None,
) -> tuple[ScriptProject, list[ScriptScene], list[ScriptShot]]:
    subject = db.scalar(
        select(Person).where(Person.id == payload.subject_id, Person.tenant_id == tenant_id)
    )
    if subject is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.SUBJECT_NOT_FOUND)

    claim_statement = select(MemoryClaim).where(
        MemoryClaim.tenant_id == tenant_id,
        MemoryClaim.subject_id == payload.subject_id,
    )
    if payload.chapter_id:
        claim_statement = claim_statement.where(MemoryClaim.chapter_id == payload.chapter_id)
    claims = list(db.scalars(claim_statement.order_by(MemoryClaim.created_at)))
    if not claims:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.SCRIPT_MEMORIES_REQUIRED)

    subject_name = subject.preferred_name or subject.display_name
    default_title = f"{subject_name}的岁月片段"
    usable_claims = [item for item in claims if item.review_status not in {"disputed", "private"}]
    if not usable_claims:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.SCRIPT_MEMORIES_REQUIRED)

    grouped_claims: dict[UUID | None, list[MemoryClaim]] = {}
    if payload.mode == "multi_chapter" and payload.chapter_id is None:
        for claim in usable_claims:
            grouped_claims.setdefault(claim.chapter_id, []).append(claim)
    else:
        grouped_claims[payload.chapter_id] = usable_claims

    settings = get_settings()
    generation_provider = "rule"
    generation_model = None
    generated_title = None
    scene_payloads: list[dict] = []
    selected_claims: list[MemoryClaim] = []
    for chapter_id, chapter_claims in grouped_claims.items():
        # A chapter is regenerated from its full accepted memory set on every turn.
        selected = chapter_claims
        selected_claims.extend(selected)
        chapter = db.get(Chapter, chapter_id) if chapter_id else None
        profile = get_chapter_prompt_profile(chapter)
        chapter_brief = {
            **(update_brief or {}),
            "chapter_id": str(chapter_id) if chapter_id else None,
            "chapter_profile": profile,
            "update_mode": "replace_current_chapter",
        }
        current_scene = db.scalar(select(ScriptScene).join(ScriptProject).where(
            ScriptProject.tenant_id == tenant_id, ScriptProject.subject_id == subject.id,
            ScriptProject.status != "superseded", ScriptScene.chapter_id == chapter_id,
        ))
        if current_scene:
            current_shots = list(db.scalars(select(ScriptShot).where(
                ScriptShot.scene_id == current_scene.id,
            ).order_by(ScriptShot.order_index)))
            chapter_brief["current_script"] = {
                "heading": current_scene.heading, "plot": current_scene.plot,
                "dialogues": current_scene.dialogues, "narration": current_scene.narration,
                "visual_prompt": current_scene.visual_prompt,
                "shots": [{"visual_prompt": shot.visual_prompt, "shot_type": shot.shot_type,
                           "duration_seconds": shot.duration_seconds} for shot in current_shots],
            }
        chapter_payload = payload.model_copy(
            update={"chapter_id": chapter_id, "mode": "single_chapter"}
        )
        # Applies to mock as well, including old claims created before document
        # extraction had a budget. Never silently drop all claims after number 40.
        _script_input({
            "claims": [{"claim_id": str(claim.id), "claim_text": claim.claim_text,
                        "source_quote": claim.source_quote} for claim in selected],
            "update_brief": chapter_brief,
        })
        if settings.llm_provider == "openai-compatible":
            title, generated, generation_model = _llm_scenes(
                subject,
                chapter_payload,
                selected,
                profile,
                chapter_brief,
            )
            generated_title = generated_title or title
            generation_provider = "openai-compatible"
        elif settings.llm_provider == "mock":
            generated = _rule_scenes(subject_name, selected, profile)
        else:
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                ErrorCode.SCRIPT_LLM_CONFIGURATION_INCOMPLETE,
            )
        if not isinstance(generated, list) or len(generated) != 1:
            raise ApiError(502, ErrorCode.SCRIPT_LLM_RESPONSE_INVALID)
        for scene_payload in generated:
            validated = _validate_generated_scene(scene_payload, {str(c.id) for c in selected})
            scene_payloads.append({**validated, "chapter_id": chapter_id})
    project = db.scalar(
        select(ScriptProject).where(
            ScriptProject.tenant_id == tenant_id,
            ScriptProject.subject_id == subject.id,
            ScriptProject.status != "superseded",
        )
    )
    existing_scenes: list[ScriptScene] = []
    if project is None:
        project = ScriptProject(
            tenant_id=tenant_id,
            subject_id=subject.id,
            title=payload.title or generated_title or default_title,
            mode=payload.mode,
            audience=payload.audience,
            source_claim_ids=[],
            status="draft",
            review_status="needs_review",
            generation_provider=generation_provider,
            generation_model=generation_model,
        )
        db.add(project)
    else:
        _, existing_scenes, _ = get_project(db, tenant_id, project.id)
        project.title = payload.title or project.title
        project.mode = payload.mode
        project.audience = payload.audience
        project.status = "draft"
        project.locked_at = None
        project.version_number += 1
        project.generation_provider = generation_provider
        project.generation_model = generation_model
    db.flush()

    replace_all = payload.mode == "multi_chapter" or payload.chapter_id is None
    replaced_scenes = (
        existing_scenes
        if replace_all
        else [scene for scene in existing_scenes if scene.chapter_id == payload.chapter_id]
    )
    replaced_ids = [scene.id for scene in replaced_scenes]
    saved_references = {scene.chapter_id: scene.reference_asset_ids for scene in replaced_scenes}
    if replaced_ids:
        db.execute(delete(ScriptShot).where(ScriptShot.scene_id.in_(replaced_ids)))
        db.execute(delete(ScriptScene).where(ScriptScene.id.in_(replaced_ids)))
        db.flush()

    remaining_scenes = [scene for scene in existing_scenes if scene.id not in replaced_ids]
    insert_at = min(
        (scene.order_index for scene in replaced_scenes),
        default=len(remaining_scenes) + 1,
    )
    created_scenes: list[ScriptScene] = []
    for offset, scene_payload in enumerate(scene_payloads):
        scene = ScriptScene(
            tenant_id=tenant_id,
            project_id=project.id,
            chapter_id=scene_payload["chapter_id"],
            reference_asset_ids=saved_references.get(scene_payload["chapter_id"]),
            order_index=insert_at + offset,
            heading=scene_payload["heading"],
            plot=scene_payload.get("plot"),
            dialogues=scene_payload.get("dialogues"),
            narration=scene_payload["narration"],
            visual_prompt=scene_payload["visual_prompt"],
            duration_seconds=scene_payload["duration_seconds"],
            source_claim_ids=scene_payload["source_claim_ids"],
            review_status="needs_review",
        )
        db.add(scene)
        db.flush()
        created_scenes.append(scene)
        db.add_all(
            [
                ScriptShot(
                    tenant_id=tenant_id,
                    scene_id=scene.id,
                    order_index=shot_index,
                    shot_type=shot["shot_type"],
                    visual_prompt=shot["visual_prompt"],
                    duration_seconds=shot["duration_seconds"],
                    source_claim_ids=shot["source_claim_ids"],
                )
                for shot_index, shot in enumerate(scene_payload["shots"], start=1)
            ]
        )

    db.flush()
    all_scenes = sorted([*remaining_scenes, *created_scenes], key=lambda scene: scene.order_index)
    for order_index, scene in enumerate(all_scenes, start=1):
        scene.order_index = order_index
    project.source_claim_ids = list(
        dict.fromkeys(claim_id for scene in all_scenes for claim_id in scene.source_claim_ids)
    )
    for key in billing_keys or []:
        charge = db.scalar(
            select(Charge).where(
                Charge.tenant_id == tenant_id,
                Charge.business_key == key,
            )
        )
        charge.price_snapshot = {**charge.price_snapshot, "result_project_id": str(project.id)}
        db.flush()
        billing.transition(db, tenant_id, key, True)
    db.commit()
    return get_project(db, tenant_id, project.id)


def update_scene(db, tenant_id, project_id, scene_id, payload: ScriptSceneUpdate):
    project, _, _ = get_project(db, tenant_id, project_id)
    with execution_lock(db, project.subject_id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.SCRIPT_EDIT_BUSY)
        db.refresh(project)
        if project.version_number != payload.expected_version:
            raise ApiError(409, ErrorCode.SCRIPT_EDIT_CONFLICT)
        scene = db.scalar(select(ScriptScene).where(
            ScriptScene.id == scene_id, ScriptScene.project_id == project_id,
            ScriptScene.tenant_id == tenant_id,
        ))
        if scene is None:
            raise ApiError(409, ErrorCode.SCRIPT_EDIT_CONFLICT)
        busy = db.scalar(select(InterviewTurnWorkflow.id).join(InterviewSession).where(
            InterviewSession.subject_id == project.subject_id,
            InterviewTurnWorkflow.tenant_id == tenant_id,
            InterviewTurnWorkflow.status.in_(["queued", "running"]),
        ).limit(1))
        if busy:
            raise ApiError(409, ErrorCode.SCRIPT_EDIT_BUSY)
        if (payload.shots and sum(shot.duration_seconds for shot in payload.shots)
                != payload.duration_seconds) or any(
            not line.speaker.strip() or not line.text.strip() for line in payload.dialogues
        ):
            raise ApiError(422, ErrorCode.SCRIPT_CONTENT_INVALID)
        scene.heading = payload.heading
        scene.plot = payload.plot or None
        scene.dialogues = [line.model_dump() for line in payload.dialogues]
        scene.narration = "\n".join(line.text for line in payload.dialogues)
        scene.visual_prompt = payload.visual_prompt
        scene.duration_seconds = payload.duration_seconds
        old_shots = list(db.scalars(select(ScriptShot).where(ScriptShot.scene_id == scene.id)
                                   .order_by(ScriptShot.order_index)))
        db.execute(delete(ScriptShot).where(ScriptShot.scene_id == scene.id))
        for index, shot in enumerate(payload.shots):
            previous = old_shots[index] if index < len(old_shots) else None
            sources = previous.source_claim_ids if (
                previous and previous.visual_prompt == shot.visual_prompt
            ) else []
            db.add(ScriptShot(tenant_id=tenant_id, scene_id=scene.id, order_index=index + 1,
                              **shot.model_dump(), source_claim_ids=sources))
        project.version_number += 1
        project.status = "draft"
        db.commit()
        return get_project(db, tenant_id, project.id)

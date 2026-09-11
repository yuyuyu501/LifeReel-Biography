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
from lifereel_api.modules.billing import service as billing
from lifereel_api.modules.billing.models import Charge
from lifereel_api.modules.billing.usage import track_usage
from lifereel_api.modules.identity.models import Person
from lifereel_api.modules.interview.chapter_prompts import (
    ChapterPromptProfile,
    get_chapter_prompt_profile,
)
from lifereel_api.modules.interview.models import Chapter
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.modules.script.models import ScriptProject, ScriptScene, ScriptShot
from lifereel_api.modules.script.schemas import ScriptGenerateRequest
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

logger = logging.getLogger(__name__)


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
    memories = "\n\n".join(claim.claim_text.rstrip("。") + "。" for claim in claims)
    introduction = f"我是{subject_name}。" if chapter_title == "我是谁" else ""
    visual_prompt = (
        f"围绕“{chapter_title}”的纪实电影画面，符合人物年代与地域；"
        "只呈现来源记忆中已有的细节，不得擅自生成未经授权的真实人脸。"
    )
    duration = max(12, min(90, len(claims) * 12))
    return [
        {
            "heading": chapter_title,
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
    }
    try:
        result = client.chat_json(
            f"你是中文口述史短视频编剧。当前只能写“{profile['title']}”这一章，"
            f"写作目标是：{profile['script_goal']}。只使用 evidence_pack 中与 chapter_profile"
            "相关的信息，不得引入其他生命章节，不得补写未提供的事实。每次调用都要把全部"
            "证据融合为一份完整、连续的当前章节稿件，而不是新增草稿、场景或片段列表。"
            "使用第一人称、自然口语和克制情感；新信息应融入原有叙事并改善连贯性。"
            "chapter.source_claim_ids 和每个镜头的 source_claim_ids 必须填写实际支撑内容的"
            "claim_id，且只能引用输入中的 claim_id。未核对信息保留不确定语气。"
            "输出严格 JSON，结构为："
            '{"title":"整本书名（可选）","chapter":{"heading":"本章标题",'
            '"narration":"一份连续的本章旁白","visual_prompt":"本章整体画面方向",'
            '"duration_seconds":30,"source_claim_ids":["..."],'
            '"shots":[{"shot_type":"wide|medium|closeup|detail|archive",'
            '"visual_prompt":"...","duration_seconds":6,"source_claim_ids":["..."]}]}}。',
            json.dumps(request, ensure_ascii=False),
        )
    except json.JSONDecodeError as exc:
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.SCRIPT_LLM_RESPONSE_INVALID,
        ) from exc
    except ApiError:
        raise
    except Exception as exc:
        logger.exception("Script generation provider request failed", exc_info=exc)
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.SCRIPT_LLM_REQUEST_FAILED,
        ) from exc

    allowed_ids = {str(claim.id) for claim in claims}
    raw_chapter = result.get("chapter")
    if not isinstance(raw_chapter, dict):
        logger.warning(
            "Invalid script model response: chapter_type=%s response_keys=%s",
            type(raw_chapter).__name__,
            sorted(result.keys()),
        )
        raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.SCRIPT_LLM_RESPONSE_INVALID)
    try:
        raw_source_ids = [str(value) for value in raw_chapter["source_claim_ids"]]
        source_ids = list(
            dict.fromkeys(claim_id for claim_id in raw_source_ids if claim_id in allowed_ids)
        )
        if not source_ids:
            raise ValueError("chapter has no valid evidence references")
        duration = max(4, min(180, int(raw_chapter.get("duration_seconds", 30))))
        shots = []
        for raw_shot in (raw_chapter.get("shots") or [])[:12]:
            if not isinstance(raw_shot, dict):
                raise ValueError("shot is not an object")
            raw_shot_source_ids = [str(value) for value in raw_shot["source_claim_ids"]]
            shot_source_ids = list(
                dict.fromkeys(
                    claim_id for claim_id in raw_shot_source_ids if claim_id in allowed_ids
                )
            )
            visual_prompt = str(raw_shot["visual_prompt"]).strip()
            if not shot_source_ids or not visual_prompt:
                raise ValueError("shot has no valid evidence or visual prompt")
            source_ids.extend(
                claim_id for claim_id in shot_source_ids if claim_id not in source_ids
            )
            shots.append(
                {
                    "shot_type": str(raw_shot.get("shot_type") or "medium")[:48],
                    "visual_prompt": visual_prompt,
                    "duration_seconds": max(
                        2, min(duration, int(raw_shot.get("duration_seconds", 6)))
                    ),
                    "source_claim_ids": shot_source_ids,
                }
            )
        if not shots:
            raise ValueError("chapter has no generated shots")
        shots = _fit_shot_durations(shots, duration)
        heading = str(raw_chapter.get("heading") or profile["title"]).strip()[:180]
        narration = str(raw_chapter["narration"]).strip()
        visual_prompt = str(raw_chapter["visual_prompt"]).strip()
        if not heading or not narration or not visual_prompt:
            raise ValueError("chapter text is empty")
        scene = {
            "heading": heading,
            "narration": narration,
            "visual_prompt": visual_prompt,
            "duration_seconds": duration,
            "source_claim_ids": source_ids,
            "shots": shots,
        }
    except (KeyError, TypeError, ValueError, StopIteration) as exc:
        logger.warning(
            "Invalid script model response: reason=%s allowed_claim_count=%s",
            exc,
            len(allowed_ids),
        )
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.SCRIPT_LLM_RESPONSE_INVALID,
        ) from exc
    return str(result.get("title") or "").strip()[:180] or None, [scene], model


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
        selected = chapter_claims[:40]
        selected_claims.extend(selected)
        chapter = db.get(Chapter, chapter_id) if chapter_id else None
        profile = get_chapter_prompt_profile(chapter)
        chapter_brief = {
            **(update_brief or {}),
            "chapter_id": str(chapter_id) if chapter_id else None,
            "chapter_profile": profile,
            "update_mode": "replace_current_chapter",
        }
        chapter_payload = payload.model_copy(
            update={"chapter_id": chapter_id, "mode": "single_chapter"}
        )
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
        for scene_payload in generated:
            scene_payloads.append({**scene_payload, "chapter_id": chapter_id})
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
            order_index=insert_at + offset,
            heading=scene_payload["heading"],
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

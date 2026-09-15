from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing import service as billing
from lifereel_api.modules.billing.usage import track_usage
from lifereel_api.modules.evidence import service as evidence_service
from lifereel_api.modules.evidence.models import EvidenceObservation, SourceAsset
from lifereel_api.modules.interview import service as interview_service
from lifereel_api.modules.interview.chapter_prompts import get_chapter_prompt_profile
from lifereel_api.modules.interview.models import (
    Chapter,
    InterviewRound,
    InterviewSession,
    InterviewTurnWorkflow,
)
from lifereel_api.modules.interview.schemas import InterviewRoundCreate, InterviewTurnCreate
from lifereel_api.modules.jobs import service as job_service
from lifereel_api.modules.memory import recovery as memory_recovery
from lifereel_api.modules.memory import service as memory_service
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.modules.memory.schemas import MemoryCompileRequest
from lifereel_api.modules.script import service as script_service
from lifereel_api.modules.script.models import ScriptProject
from lifereel_api.modules.script.schemas import ScriptGenerateRequest, ScriptProjectRead
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


def _get_workflow(db: Session, tenant_id: UUID, workflow_id: UUID) -> InterviewTurnWorkflow:
    workflow = db.scalar(
        select(InterviewTurnWorkflow).where(
            InterviewTurnWorkflow.id == workflow_id,
            InterviewTurnWorkflow.tenant_id == tenant_id,
        )
    )
    if workflow is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.INTERVIEW_TURN_NOT_FOUND)
    return workflow


def _asset_payload(asset: SourceAsset) -> dict:
    return {
        "id": str(asset.id),
        "subject_id": str(asset.subject_id),
        "interview_session_id": (
            str(asset.interview_session_id) if asset.interview_session_id else None
        ),
        "kind": asset.kind,
        "original_filename": asset.original_filename,
        "mime_type": asset.mime_type,
        "byte_size": asset.byte_size,
        "sha256": asset.sha256,
        "status": asset.status,
        "consent_scope": asset.consent_scope,
        "captured_at": asset.captured_at,
        "created_at": asset.created_at,
    }


def _script_payload(db: Session, tenant_id: UUID, subject_id: UUID) -> dict | None:
    project = db.scalar(
        select(ScriptProject).where(
            ScriptProject.tenant_id == tenant_id,
            ScriptProject.subject_id == subject_id,
            ScriptProject.status != "superseded",
        )
    )
    if project is None:
        return None
    project, scenes, shots = script_service.get_project(db, tenant_id, project.id)
    return (
        ScriptProjectRead.model_validate(project)
        .model_copy(update={"scenes": scenes, "shots": shots})
        .model_dump(mode="json")
    )


def get_workspace(db: Session, tenant_id: UUID, session_id: UUID) -> dict:
    session = interview_service.get_session(db, tenant_id, session_id)
    assets = list(
        db.scalars(
            select(SourceAsset)
            .where(
                SourceAsset.tenant_id == tenant_id,
                SourceAsset.subject_id == session.subject_id,
                SourceAsset.interview_session_id == session.id,
            )
            .order_by(SourceAsset.created_at)
        )
    )
    latest = db.scalar(
        select(InterviewTurnWorkflow)
        .where(
            InterviewTurnWorkflow.tenant_id == tenant_id,
            InterviewTurnWorkflow.session_id == session.id,
        )
        .order_by(InterviewTurnWorkflow.created_at.desc())
        .limit(1)
    )
    return {
        "session": session,
        "assets": [_asset_payload(item) for item in assets],
        "script": _script_payload(db, tenant_id, session.subject_id),
        "latest_workflow": latest,
    }


def create_turn(
    db: Session,
    tenant_id: UUID,
    session_id: UUID,
    payload: InterviewTurnCreate,
) -> InterviewTurnWorkflow:
    # Serialize submissions so two tabs cannot create competing continuations.
    if (
        db.scalar(
            select(InterviewSession.id)
            .where(
                InterviewSession.id == session_id,
                InterviewSession.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        is None
    ):
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.INTERVIEW_NOT_FOUND)
    existing = db.scalar(
        select(InterviewTurnWorkflow).where(
            InterviewTurnWorkflow.tenant_id == tenant_id,
            InterviewTurnWorkflow.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if existing.session_id != session_id:
            raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.INTERVIEW_TURN_STATE_INVALID)
        return existing
    if (not (payload.answer_text or "").strip() and not payload.asset_ids
            and payload.action == "interview"):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ErrorCode.INTERVIEW_TURN_CONTENT_REQUIRED,
        )

    session = interview_service.get_session(db, tenant_id, session_id)
    latest = db.scalar(
        select(InterviewTurnWorkflow)
        .where(
            InterviewTurnWorkflow.session_id == session.id,
            InterviewTurnWorkflow.tenant_id == tenant_id,
        )
        .order_by(InterviewTurnWorkflow.created_at.desc())
        .limit(1)
    )
    if latest and latest.status in {"queued", "running"}:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.INTERVIEW_TURN_STATE_INVALID)
    if payload.action == "regenerate_script":
        current = session.rounds[-1] if session.rounds else None
        round_ = InterviewRound(
            tenant_id=tenant_id, session_id=session.id,
            round_index=(current.round_index if current else 0) + 1,
            question_text="", question_source="script_request",
        )
        db.add(round_)
        db.flush()
        session.round_count = round_.round_index
    elif payload.round_id is not None:
        round_ = db.scalar(
            select(InterviewRound).where(
                InterviewRound.id == payload.round_id,
                InterviewRound.session_id == session.id,
                InterviewRound.tenant_id == tenant_id,
            )
        )
        if round_ is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.INTERVIEW_ROUND_NOT_FOUND)
    else:
        current = session.rounds[-1] if session.rounds else None
        if current and not current.answer_text:
            round_ = current
        else:
            # A continuation is a user message, not a fabricated AI question.
            round_ = InterviewRound(
                tenant_id=tenant_id,
                session_id=session.id,
                round_index=(current.round_index if current else 0) + 1,
                question_text="",
                question_source="user_continuation",
            )
            db.add(round_)
            db.flush()
            session.round_count = round_.round_index
    if round_.answer_text:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.INTERVIEW_TURN_STATE_INVALID)

    assets = (
        list(
            db.scalars(
                select(SourceAsset).where(
                    SourceAsset.id.in_(payload.asset_ids),
                    SourceAsset.tenant_id == tenant_id,
                    SourceAsset.subject_id == session.subject_id,
                )
            )
        )
        if payload.asset_ids
        else []
    )
    if len(assets) != len(set(payload.asset_ids)):
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.EVIDENCE_ASSET_NOT_FOUND)
    for asset in assets:
        if asset.interview_session_id is None:
            asset.interview_session_id = session.id
        elif asset.interview_session_id != session.id:
            raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.EVIDENCE_ASSET_NOT_FOUND)

    answer_text = (payload.answer_text or "").strip()
    if payload.action == "regenerate_script" and not answer_text:
        answer_text = "请根据已讲述的内容重新生成本章剧本。"
    if answer_text:
        round_.answer_text = answer_text
        round_.source_asset_id = assets[0].id if assets else None
        round_.answered_at = datetime.now(UTC)
        round_.transcript_status = "done"

    workflow = InterviewTurnWorkflow(
        tenant_id=tenant_id,
        session_id=session.id,
        round_id=round_.id,
        chapter_id=session.chapter_id,
        idempotency_key=payload.idempotency_key,
        status="queued",
        script_brief={"requested_action": payload.action},
        # Continue unfinished material analysis together with the new message.
        asset_ids=list(dict.fromkeys([
            *(latest.asset_ids if latest and latest.status == "failed" else []),
            *(str(item.id) for item in assets),
        ])),
    )
    db.add(workflow)
    db.flush()
    job, _ = job_service.create_job(
        db,
        tenant_id,
        "interview.turn.process",
        {"workflow_id": str(workflow.id)},
        f"interview-turn:{workflow.id}",
    )
    workflow.job_id = job.id
    db.commit()
    db.refresh(workflow)

    settings = get_settings()
    if settings.llm_provider == "mock" and settings.execute_mock_jobs_inline:
        return execute_turn(db, tenant_id, workflow.id)
    job_service.enqueue(job)
    return workflow


def _rule_missing_topics(
    claims: list[MemoryClaim],
    rounds: list[InterviewRound],
    chapter: Chapter | None,
) -> list[str]:
    text = "\n".join(claim.claim_text for claim in claims)
    intents = {item.question_intent for item in rounds if item.answer_text}
    generic_checks = [
        ("时间", any(char.isdigit() for char in text) or "timeline" in intents),
        ("地点", any(word in text for word in ("在", "村", "镇", "县", "市", "学校", "家乡"))),
        ("关键人物", any(word in text for word in ("父", "母", "老师", "朋友", "同学", "家人"))),
        ("事情经过", len(text) >= 80 or "event" in intents),
        (
            "当时感受",
            any(word in text for word in ("觉得", "感到", "高兴", "难过", "害怕", "温暖")),
        ),
        ("后来影响", any(word in text for word in ("后来", "影响", "从此", "因此", "直到现在"))),
    ]
    profile = get_chapter_prompt_profile(chapter)
    missing_required = [
        topic
        for topic in profile["required_topics"]
        if not any(keyword in text for keyword in _topic_terms(topic, profile["keywords"]))
    ]
    missing_generic = [topic for topic, covered in generic_checks if not covered]
    return list(dict.fromkeys([*missing_required, *missing_generic]))[:4]


def _validate_assessment(result) -> dict:
    if not isinstance(result, dict):
        raise ValueError("ASSESSMENT_OBJECT_REQUIRED")
    raw_topics = result.get("missing_topics")
    if not isinstance(raw_topics, list) or any(not isinstance(item, str) for item in raw_topics):
        raise ValueError("ASSESSMENT_TOPICS_INVALID")
    topics = list(dict.fromkeys(item.strip() for item in raw_topics if item.strip()))
    if len(topics) > 4 or any(len(item) > 120 for item in topics):
        raise ValueError("ASSESSMENT_TOPICS_LIMIT")
    ready, reason = result.get("ready_for_script"), result.get("reason")
    if type(ready) is not bool:
        raise ValueError("ASSESSMENT_READINESS_INVALID")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("ASSESSMENT_REASON_REQUIRED")
    return {"missing_topics": topics, "ready_for_script": ready, "reason": reason.strip()[:500]}


def _assess_chapter(
    db: Session,
    tenant_id: UUID,
    claims: list[MemoryClaim],
    rounds: list[InterviewRound],
    chapter: Chapter | None,
) -> dict:
    settings = get_settings()
    if settings.llm_provider == "mock":
        return {
            "missing_topics": _rule_missing_topics(claims, rounds, chapter),
            "ready_for_script": bool(claims),
            "reason": "mock assessment",
        }
    if settings.llm_provider != "openai-compatible":
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.INTERVIEW_LLM_CONFIGURATION_INCOMPLETE,
        )

    profile = get_chapter_prompt_profile(chapter)
    client = OpenAICompatibleClient(
        settings.openai_compatible_base_url or "",
        settings.openai_compatible_api_key or "",
        settings.model_for("interview"),
    )
    if not client.capabilities().configured:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.INTERVIEW_LLM_CONFIGURATION_INCOMPLETE,
        )
    context = {
        "chapter": profile,
        "claims": [
            {"claim_text": claim.claim_text, "source_quote": claim.source_quote}
            for claim in claims[-40:]
        ],
        "answered_rounds": [
            {"question": round_.question_text, "answer": round_.answer_text}
            for round_ in rounds[-12:]
            if round_.answer_text
        ],
    }
    allowed_topics = [
        *profile["required_topics"],
        "时间",
        "地点",
        "关键人物",
        "事情经过",
        "当时感受",
        "后来影响",
    ]
    system = (
        "你是中文口述史采访规划师。请根据当前章节画像、已确认记忆和完整对话，"
        "语义判断当前章节还缺少哪些最重要的信息。只输出 JSON，missing_topics 必须是"
        "字符串数组，最多 4 项，每项不超过120字；allowed_topics仅供参考，允许使用"
        "本章具体缺失细节的自然语言描述，不必逐字匹配词表。不得根据关键词匹配"
        "或字数猜测，不得把其他章节内容当作当前章节缺口。还要语义判断现有证据能否"
        "支撑一段不虚构事实、包含旁白和画面描述的本章短剧本。只提供姓名、问候、"
        "拒绝回答或离题内容时，ready_for_script 为 false，继续采访，不强行编剧。"
        "已有具体生活细节可成稿时可以为 true，不要求所有主题完整，也不按记忆条数判断。"
        "用户要求重写剧本时，应依据已有claims判断是否可生成，不要求用户重复讲述。"
        "评估目标是含剧情、分镜、人物对话（可只有旁白）、场景描述的四部分剧本。"
        "reason 简要说明依据。格式："
        '{"missing_topics":["..."],"ready_for_script":false,"reason":"..."}。'
    )
    issues = []
    for attempt in range(2):
        retry_hint = (
            "\n上次返回未通过格式校验，原因码：" + issues[-1]
            + "。请根据原始资料重新输出完整JSON；信息不足时正常返回false，不要强行编剧。"
            if attempt else ""
        )
        try:
            result = client.chat_json(
                system + retry_hint,
                json.dumps({**context, "allowed_topics": allowed_topics}, ensure_ascii=False),
            )
        except json.JSONDecodeError:
            issues.append("ASSESSMENT_JSON_INVALID")
            continue
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError(502, ErrorCode.INTERVIEW_LLM_REQUEST_FAILED) from exc
        try:
            return _validate_assessment(result)
        except ValueError as exc:
            issues.append(str(exc))
    error = ApiError(502, ErrorCode.INTERVIEW_LLM_RESPONSE_INVALID)
    error.diagnostic = {"stage": "chapter_assessment", "issues": issues}
    raise error


def _missing_topics(db, tenant_id, claims, rounds, chapter) -> list[str]:
    return _assess_chapter(db, tenant_id, claims, rounds, chapter)["missing_topics"]


def _topic_terms(topic: str, chapter_keywords: list[str]) -> list[str]:
    terms = [term for term in chapter_keywords if term in topic or topic in term]
    return [topic, *terms]


def _new_claims_for_workflow(
    db: Session, tenant_id: UUID, workflow: InterviewTurnWorkflow
) -> list[MemoryClaim]:
    observation_ids = (
        list(
            db.scalars(
                select(EvidenceObservation.id).where(
                    EvidenceObservation.tenant_id == tenant_id,
                    EvidenceObservation.source_asset_id.in_(
                        [UUID(item) for item in workflow.asset_ids]
                    ),
                )
            )
        )
        if workflow.asset_ids
        else []
    )
    statement = select(MemoryClaim).where(MemoryClaim.tenant_id == tenant_id)
    conditions = [MemoryClaim.source_round_id == workflow.round_id]
    if observation_ids:
        conditions.append(MemoryClaim.source_observation_id.in_(observation_ids))
    from sqlalchemy import or_

    return list(db.scalars(statement.where(or_(*conditions)).order_by(MemoryClaim.created_at)))


def _complete_turn_follow_up(
    db: Session, tenant_id: UUID, workflow: InterviewTurnWorkflow
) -> InterviewTurnWorkflow:
    next_question = interview_service.suggest_next_question(
        db,
        tenant_id,
        workflow.session_id,
        assessment=workflow.script_brief["assessment"],
    )
    # add_round commits the response and completed workflow in the same transaction.
    workflow.status = "completed"
    workflow.next_question = next_question["question_text"]
    workflow.next_question_intent = next_question["question_intent"]
    workflow.completed_at = datetime.now(UTC)
    interview_service.add_round(
        db,
        tenant_id,
        workflow.session_id,
        InterviewRoundCreate(
            question_text=next_question["question_text"],
            question_intent=next_question["question_intent"],
            question_source=next_question["question_source"],
        ),
    )
    db.refresh(workflow)
    if workflow.job_id:
        job_service.complete_job(
            db,
            tenant_id,
            workflow.job_id,
            {
                "workflow_id": str(workflow.id),
                "script_project_id": (
                    str(workflow.script_project_id) if workflow.script_project_id else None
                ),
            },
        )
    return workflow


@track_usage("interview")
def execute_turn(
    db: Session, tenant_id: UUID, workflow_id: UUID, *, recover_interrupted: bool = False,
) -> InterviewTurnWorkflow:
    from lifereel_api.modules.production.locking import execution_lock

    workflow = _get_workflow(db, tenant_id, workflow_id)
    session = db.get(InterviewSession, workflow.session_id)
    # Chapters share one person's graph and biography, so serialize that person's updates.
    lock_key = uuid5(NAMESPACE_URL, f"lifereel:interview:{session.subject_id}")
    with execution_lock(db, lock_key) as acquired:
        if not acquired:
            # Duplicate queue delivery must not mark the active execution failed.
            return workflow
        return _execute_turn(db, tenant_id, workflow_id, recover_interrupted=recover_interrupted)


def _execute_turn(
    db: Session, tenant_id: UUID, workflow_id: UUID, *, recover_interrupted: bool = False,
) -> InterviewTurnWorkflow:
    workflow = _get_workflow(db, tenant_id, workflow_id)
    if workflow.status == "completed":
        return workflow
    # Share the submission lock so an old retry cannot race a continuation.
    db.scalar(
        select(InterviewSession.id)
        .where(InterviewSession.id == workflow.session_id, InterviewSession.tenant_id == tenant_id)
        .with_for_update()
    )
    db.refresh(workflow)
    latest_id = db.scalar(
        select(InterviewTurnWorkflow.id)
        .where(
            InterviewTurnWorkflow.session_id == workflow.session_id,
            InterviewTurnWorkflow.tenant_id == tenant_id,
        )
        .order_by(InterviewTurnWorkflow.created_at.desc())
        .limit(1)
    )
    if latest_id != workflow.id:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.INTERVIEW_TURN_STATE_INVALID)
    if workflow.status == "completed":
        return workflow
    if workflow.status == "running" and not recover_interrupted:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.INTERVIEW_TURN_STATE_INVALID)
    if workflow.status == "running":
        from lifereel_api.modules.billing.models import Charge

        # A crashed paid call without a receipt must be reconciled, not resubmitted.
        holds = db.scalars(select(Charge).where(
            Charge.tenant_id == tenant_id, Charge.kind == "token_hold", Charge.status == "reserved",
        ))
        if any(h.price_snapshot.get("reference") == str(workflow.id) for h in holds):
            workflow.status = "failed"
            workflow.error_code = ErrorCode.BILLING_USAGE_PENDING.value
            db.commit()
            job_service.fail_job(db, tenant_id, workflow.job_id, workflow.error_code, None)
            return workflow
    if workflow.status == "failed" and memory_recovery.retry_after(workflow):
        raise ApiError(409, ErrorCode.MEMORY_RETRY_COOLDOWN)

    workflow.status = "running"
    workflow.error_code = None
    if workflow.job_id:
        job = job_service.get_job(db, tenant_id, workflow.job_id)
        job.status = "running"
        job.attempt_count += 1
    db.commit()

    billing_key = None
    try:
        memory_recovery.begin(db, workflow)
        if workflow.script_brief.get("followup_ready") is True:
            return _complete_turn_follow_up(db, tenant_id, workflow)
        session = interview_service.get_session(db, tenant_id, workflow.session_id)
        script_request = ScriptGenerateRequest(
            subject_id=session.subject_id,
            chapter_id=session.chapter_id,
            idempotency_key=workflow.id,
            mode="single_chapter",
            audience="family",
        )
        billing_key = script_service.reserve_interview_update(db, tenant_id, script_request)
        db.commit()
        for asset_id in workflow.asset_ids:
            asset_uuid = UUID(asset_id)
            existing = db.scalar(
                select(EvidenceObservation.id).where(
                    EvidenceObservation.tenant_id == tenant_id,
                    EvidenceObservation.source_asset_id == asset_uuid,
                )
            )
            if existing is None:
                evidence_service.analyze_asset(db, tenant_id, asset_uuid)

        source_round = db.get(InterviewRound, workflow.round_id)
        if source_round and not source_round.answer_text and workflow.asset_ids:
            spoken_observation = db.scalar(
                select(EvidenceObservation)
                .join(SourceAsset, SourceAsset.id == EvidenceObservation.source_asset_id)
                .where(
                    EvidenceObservation.tenant_id == tenant_id,
                    EvidenceObservation.source_asset_id.in_(
                        [UUID(item) for item in workflow.asset_ids]
                    ),
                    SourceAsset.kind.in_(["audio", "video"]),
                    EvidenceObservation.confidence > 0,
                )
                .order_by(EvidenceObservation.created_at.desc())
                .limit(1)
            )
            if spoken_observation is not None:
                source_round.answer_text = spoken_observation.text
                source_round.source_asset_id = spoken_observation.source_asset_id
                source_round.answered_at = datetime.now(UTC)
                source_round.transcript_status = "done"
                db.commit()

        from lifereel_api.modules.orchestration.intent import classify_turn

        intent = workflow.script_brief.get("turn_intent")
        if intent is None:
            intent = ({"action": "regenerate_script", "has_new_facts": False,
                       "instructions": source_round.answer_text or ""}
                      if workflow.script_brief.get("requested_action") == "regenerate_script"
                      else classify_turn(source_round.answer_text or ""))
            workflow.script_brief = {**workflow.script_brief, "turn_intent": intent}
            if not intent["has_new_facts"]:
                source_round.question_source = "script_request"
            db.commit()

        memory_service.compile_memories(
            db,
            tenant_id,
            MemoryCompileRequest(interview_session_id=session.id),
        )
        chapter_claims = list(
            db.scalars(
                select(MemoryClaim)
                .where(
                    MemoryClaim.tenant_id == tenant_id,
                    MemoryClaim.subject_id == session.subject_id,
                    MemoryClaim.chapter_id == session.chapter_id,
                    MemoryClaim.review_status.not_in(["disputed", "private"]),
                )
                .order_by(MemoryClaim.created_at)
            )
        )
        new_claims = _new_claims_for_workflow(db, tenant_id, workflow)
        chapter = db.get(Chapter, session.chapter_id) if session.chapter_id else None
        profile = get_chapter_prompt_profile(chapter)
        assessment_key = hashlib.sha256(json.dumps([
            memory_recovery.fingerprint(chapter_claims), profile,
            [(r.question_text, r.answer_text) for r in session.rounds],
        ], ensure_ascii=False).encode()).hexdigest()
        saved_assessment = workflow.script_brief.get("assessment_checkpoint", {})
        if saved_assessment.get("key") == assessment_key:
            assessment = saved_assessment["result"]
        else:
            assessment = _assess_chapter(db, tenant_id, chapter_claims, session.rounds, chapter)
            workflow.script_brief = {**workflow.script_brief, "assessment_checkpoint": {
                "key": assessment_key, "result": assessment,
            }}
            db.commit()
        missing = assessment["missing_topics"]
        assessment = {**assessment, "script_action": intent["action"]}
        brief = {
            "chapter_id": str(session.chapter_id) if session.chapter_id else None,
            "chapter_title": chapter.title if chapter else "自由采访",
            "chapter_profile": profile,
            "new_facts": [
                {
                    "text": claim.claim_text,
                    "source_type": (
                        "interview_round" if claim.source_round_id else "evidence_observation"
                    ),
                    "source_id": str(claim.source_round_id or claim.source_observation_id),
                    "claim_id": str(claim.id),
                }
                for claim in new_claims
            ],
            "tone": "克制、第一人称、自然口语",
            "missing_topics": missing,
            "update_mode": "replace_current_chapter",
            "assessment": assessment,
            "script_instructions": intent["instructions"],
        }

        project = None
        scenes = []
        if chapter_claims and assessment["ready_for_script"]:
            project, scenes, _ = script_service.generate_draft(
                db,
                tenant_id,
                script_request,
                update_brief=brief,
            )
        else:
            billing.transition(db, tenant_id, billing_key, False)
            db.commit()

        assessment["script_updated"] = project is not None
        # Retain completed AI work even if the following response fails validation.
        workflow = _get_workflow(db, tenant_id, workflow.id)
        workflow.source_claim_ids = [str(item.id) for item in new_claims]
        workflow.script_project_id = project.id if project else None
        workflow.script_scene_ids = [str(item.id) for item in scenes]
        workflow.missing_topics = missing
        workflow.script_brief = {**workflow.script_brief, **brief, "followup_ready": True}
        db.commit()
        return _complete_turn_follow_up(db, tenant_id, workflow)
    except ApiError as exc:
        db.rollback()
        if billing_key:
            billing.transition(db, tenant_id, billing_key, False)
        workflow = _get_workflow(db, tenant_id, workflow_id)
        workflow.status = "failed"
        workflow.error_code = exc.code.value
        memory_recovery.failure(db, workflow, exc)
        db.commit()
        if workflow.job_id:
            job_service.fail_job(db, tenant_id, workflow.job_id, exc.code.value, None)
        raise
    except Exception:
        db.rollback()
        if billing_key:
            billing.transition(db, tenant_id, billing_key, False)
        workflow = _get_workflow(db, tenant_id, workflow_id)
        workflow.status = "failed"
        workflow.error_code = ErrorCode.WORKER_ERROR.value
        db.commit()
        if workflow.job_id:
            job_service.fail_job(db, tenant_id, workflow.job_id, ErrorCode.WORKER_ERROR.value, None)
        raise

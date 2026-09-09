from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing.usage import track_usage
from lifereel_api.modules.evidence.models import SourceAsset
from lifereel_api.modules.identity.models import Person
from lifereel_api.modules.interview.chapter_prompts import get_chapter_prompt_profile
from lifereel_api.modules.interview.models import Chapter, InterviewRound, InterviewSession
from lifereel_api.modules.interview.schemas import InterviewRoundCreate, InterviewStart
from lifereel_api.modules.memory.models import MemoryClaim, MemoryConflict
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


def _chapter_conflicts(
    db: Session,
    tenant_id: UUID,
    subject_id: UUID,
    chapter_id: UUID | None,
) -> list[MemoryConflict]:
    conflicts = list(
        db.scalars(
            select(MemoryConflict).where(
                MemoryConflict.tenant_id == tenant_id,
                MemoryConflict.subject_id == subject_id,
                MemoryConflict.status == "open",
            )
        )
    )
    if chapter_id is None:
        return conflicts
    chapter_claim_ids = {
        str(claim_id)
        for claim_id in db.scalars(
            select(MemoryClaim.id).where(
                MemoryClaim.tenant_id == tenant_id,
                MemoryClaim.subject_id == subject_id,
                MemoryClaim.chapter_id == chapter_id,
            )
        )
    }
    return [
        conflict
        for conflict in conflicts
        if any(claim_id in chapter_claim_ids for claim_id in conflict.claim_ids)
    ]


def _llm_follow_up(
    db: Session, tenant_id: UUID, session: InterviewSession, answered: list[InterviewRound]
) -> dict[str, str] | None:
    settings = get_settings()
    if settings.llm_provider == "mock":
        return None
    if settings.llm_provider != "openai-compatible":
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.INTERVIEW_LLM_CONFIGURATION_INCOMPLETE,
        )
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
    subject = db.get(Person, session.subject_id)
    chapter = db.get(Chapter, session.chapter_id) if session.chapter_id else None
    profile = get_chapter_prompt_profile(chapter)
    memory_filters = [
        MemoryClaim.tenant_id == tenant_id,
        MemoryClaim.subject_id == session.subject_id,
        MemoryClaim.review_status.in_(["verified", "unreviewed"]),
    ]
    if session.chapter_id is not None:
        memory_filters.append(MemoryClaim.chapter_id == session.chapter_id)
    memories = list(
        db.scalars(
            select(MemoryClaim)
            .where(*memory_filters)
            .order_by(MemoryClaim.created_at.desc())
            .limit(8)
        )
    )
    conflicts = _chapter_conflicts(db, tenant_id, session.subject_id, session.chapter_id)[:4]
    context = {
        "subject": {
            "name": (subject.preferred_name or subject.display_name) if subject else "讲述者",
            "birth_year": subject.birth_year if subject else None,
            "birthplace": subject.birthplace if subject else None,
        },
        "chapter": {
            "title": chapter.title if chapter else "自由采访",
            "description": chapter.description if chapter else session.topic_hint,
            "profile": profile,
        },
        "recent_rounds": [
            {"question": item.question_text, "answer": item.answer_text} for item in answered[-6:]
        ],
        "known_memories": [item.claim_text for item in memories],
        "open_conflicts": [item.description for item in conflicts],
        "answered_questions": [item.question_text for item in answered],
    }
    try:
        keywords = "、".join(profile["keywords"])
        excluded = "、".join(profile["excluded_topics"]) or "无"
        result = client.chat_json(
            f"你是尊重边界的中文口述史采访者。当前唯一采访章节是“{profile['title']}”。"
            f"本章关键词：{keywords}。本章采访目标：{profile['interview_goal']}。"
            f"越界主题：{excluded}。你只能围绕当前章节提问；用户提到越界内容时可以简短"
            "承接，但必须把下一问自然引回本章，不得继续展开其他章节。根据 required_topics"
            "和已知记忆判断缺口，每次只问一个最有价值的问题。不得臆造事实、重复"
            "answered_questions 中的问题、暗示所谓正确答案，或施压回答隐私。"
            "问题应帮助补充本章需要的时间、地点、人物、经过、影响或感受。只输出 JSON："
            '{"next_question":"...","intent":"timeline|person|place|event|consequence|feeling|meaning"}。',
            json.dumps(context, ensure_ascii=False),
        )
    except json.JSONDecodeError as exc:
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.INTERVIEW_LLM_RESPONSE_INVALID,
        ) from exc
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.INTERVIEW_LLM_REQUEST_FAILED,
        ) from exc
    if not isinstance(result, dict):
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.INTERVIEW_LLM_RESPONSE_INVALID,
        )
    question = str(result.get("next_question") or "").strip().strip('"“” ')
    intent = str(result.get("intent") or "llm_follow_up").strip()[:80]
    allowed_intents = {
        "timeline",
        "person",
        "place",
        "event",
        "consequence",
        "feeling",
        "meaning",
    }
    if not question or intent not in allowed_intents:
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.INTERVIEW_LLM_RESPONSE_INVALID,
        )
    return {"question": question[:240], "intent": intent}


def list_chapters(db: Session, tenant_id: UUID) -> list[Chapter]:
    return list(
        db.scalars(
            select(Chapter).where(Chapter.tenant_id == tenant_id).order_by(Chapter.order_index)
        )
    )


def get_session(db: Session, tenant_id: UUID, session_id: UUID) -> InterviewSession:
    session = db.scalar(
        select(InterviewSession)
        .options(selectinload(InterviewSession.rounds))
        .where(InterviewSession.id == session_id, InterviewSession.tenant_id == tenant_id)
        .execution_options(populate_existing=True)
    )
    if session is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.INTERVIEW_NOT_FOUND)
    return session


def list_sessions(db: Session, tenant_id: UUID) -> list[InterviewSession]:
    return list(
        db.scalars(
            select(InterviewSession)
            .options(selectinload(InterviewSession.rounds))
            .where(InterviewSession.tenant_id == tenant_id)
            .order_by(InterviewSession.started_at.desc())
        ).unique()
    )


def start_interview(db: Session, tenant_id: UUID, payload: InterviewStart) -> InterviewSession:
    subject = db.scalar(
        select(Person)
        .where(Person.id == payload.subject_id, Person.tenant_id == tenant_id)
        .with_for_update()
    )
    if subject is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.SUBJECT_NOT_FOUND)

    if payload.chapter_id:
        existing = db.scalar(
            select(InterviewSession)
            .where(
                InterviewSession.tenant_id == tenant_id,
                InterviewSession.subject_id == payload.subject_id,
                InterviewSession.chapter_id == payload.chapter_id,
            )
            .order_by(InterviewSession.started_at.desc())
            .limit(1)
        )
        if existing is not None:
            return get_session(db, tenant_id, existing.id)

    chapter = None
    if payload.chapter_id:
        chapter = db.scalar(
            select(Chapter).where(Chapter.id == payload.chapter_id, Chapter.tenant_id == tenant_id)
        )
        if chapter is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.CHAPTER_NOT_FOUND)

    session = InterviewSession(
        tenant_id=tenant_id,
        subject_id=payload.subject_id,
        chapter_id=payload.chapter_id,
        topic_hint=payload.topic_hint,
    )
    db.add(session)
    db.flush()

    opening = None
    if chapter and chapter.opening_questions:
        opening = chapter.opening_questions[0]
    if not opening:
        subject_name = subject.preferred_name or subject.display_name
        opening = payload.topic_hint or f"{subject_name}，您今天想从哪段往事说起？"

    db.add(
        InterviewRound(
            tenant_id=tenant_id,
            session_id=session.id,
            round_index=1,
            question_text=opening,
            question_intent="opening",
            question_source="chapter" if chapter else "topic",
        )
    )
    session.round_count = 1
    db.commit()
    return get_session(db, tenant_id, session.id)


def add_round(
    db: Session, tenant_id: UUID, session_id: UUID, payload: InterviewRoundCreate
) -> InterviewRound:
    session = get_session(db, tenant_id, session_id)
    if session.status not in {"active", "paused"}:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.INTERVIEW_INACTIVE)
    next_index = (
        db.scalar(
            select(func.max(InterviewRound.round_index)).where(
                InterviewRound.session_id == session_id
            )
        )
        or 0
    ) + 1
    round_ = InterviewRound(
        tenant_id=tenant_id,
        session_id=session_id,
        round_index=next_index,
        **payload.model_dump(),
    )
    session.status = "active"
    session.round_count = next_index
    db.add(round_)
    db.commit()
    db.refresh(round_)
    return round_


def answer_round(
    db: Session,
    tenant_id: UUID,
    session_id: UUID,
    round_id: UUID,
    answer_text: str,
    source_asset_id: UUID | None = None,
) -> InterviewRound:
    session = get_session(db, tenant_id, session_id)
    round_ = db.scalar(
        select(InterviewRound).where(
            InterviewRound.id == round_id,
            InterviewRound.session_id == session_id,
            InterviewRound.tenant_id == tenant_id,
        )
    )
    if round_ is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.INTERVIEW_ROUND_NOT_FOUND)
    if source_asset_id:
        asset = db.scalar(
            select(SourceAsset).where(
                SourceAsset.id == source_asset_id,
                SourceAsset.tenant_id == tenant_id,
                SourceAsset.subject_id == session.subject_id,
            )
        )
        if asset is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.EVIDENCE_ASSET_NOT_FOUND)
    round_.answer_text = answer_text
    round_.source_asset_id = source_asset_id
    round_.answered_at = datetime.now(UTC)
    round_.transcript_status = "done"
    db.commit()
    db.refresh(round_)
    return round_


@track_usage("question")
def suggest_next_question(db: Session, tenant_id: UUID, session_id: UUID) -> dict[str, str]:
    session = get_session(db, tenant_id, session_id)
    answered = [item for item in session.rounds if item.answer_text]
    if not answered:
        known_memory = db.scalar(
            select(MemoryClaim.id).where(
                MemoryClaim.tenant_id == tenant_id,
                MemoryClaim.subject_id == session.subject_id,
                MemoryClaim.chapter_id == session.chapter_id,
            )
        )
        if known_memory:
            llm_result = _llm_follow_up(db, tenant_id, session, answered)
            if llm_result:
                return {
                    "question_text": llm_result["question"],
                    "question_intent": llm_result["intent"],
                    "question_source": "llm_planner",
                }
        return {
            "question_text": session.rounds[-1].question_text,
            "question_intent": "opening",
            "question_source": "current_round",
        }
    if get_settings().llm_provider != "mock":
        llm_result = _llm_follow_up(db, tenant_id, session, answered)
        return {
            "question_text": llm_result["question"],
            "question_intent": llm_result["intent"],
            "question_source": "llm_planner",
        }

    # Deterministic questions are intentionally limited to the explicit mock provider.
    last_answer = answered[-1].answer_text or ""
    chapter_conflicts = _chapter_conflicts(db, tenant_id, session.subject_id, session.chapter_id)
    open_conflict = chapter_conflicts[0] if chapter_conflicts else None
    declined = any(token in last_answer for token in ("不想说", "不记得", "跳过", "不方便"))
    source = "rule_planner"
    if declined:
        question = "没关系，我们换一个轻松些的话题。那段时间里，有没有让您感到温暖的小事？"
        intent = "respect_boundary"
    elif open_conflict:
        question = (
            f"之前有一处时间信息还不太一致：{open_conflict.description}。您愿意再确认一下吗？"
        )
        intent = "conflict_resolution"
    elif len(answered) >= 6:
        question = "今天聊到这些很珍贵。最后，您最希望家人从这段经历中记住什么？"
        intent = "meaning"
    elif not any(char.isdigit() for char in last_answer) and len(answered) >= 2:
        question = "这件事大约发生在哪一年，或者当时您多大？记不清具体年份也没关系。"
        intent = "timeline_anchor"
    elif any(token in last_answer for token in ("他", "她", "父亲", "母亲", "老师", "朋友")):
        question = "您刚才提到的这个人，当时做过哪件事让您一直记到现在？"
        intent = "person_detail"
    elif any(token in last_answer for token in ("后来", "之后", "然后")):
        question = "那件事之后，您的生活发生了什么变化？"
        intent = "consequence"
    else:
        question = "如果回到当时的那个场景，您最先看到、听到或想到的是什么？"
        intent = "sensory_detail"
    return {"question_text": question, "question_intent": intent, "question_source": source}


def set_session_status(
    db: Session, tenant_id: UUID, session_id: UUID, new_status: str
) -> InterviewSession:
    session = get_session(db, tenant_id, session_id)
    session.status = new_status
    if new_status == "completed":
        session.completed_at = datetime.now(UTC)
    db.commit()
    return get_session(db, tenant_id, session_id)


def resume_session(db: Session, tenant_id: UUID, session_id: UUID) -> InterviewSession:
    session = get_session(db, tenant_id, session_id)
    session.status = "active"
    session.completed_at = None
    db.flush()

    if session.rounds and session.rounds[-1].answer_text:
        next_question = suggest_next_question(db, tenant_id, session_id)
        add_round(
            db,
            tenant_id,
            session_id,
            InterviewRoundCreate(**next_question),
        )
    else:
        db.commit()

    return get_session(db, tenant_id, session_id)

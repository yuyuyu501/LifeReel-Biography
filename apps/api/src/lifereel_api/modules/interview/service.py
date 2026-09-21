from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.processing_limits import require_memory_input
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
    db: Session,
    tenant_id: UUID,
    session: InterviewSession,
    answered: list[InterviewRound],
    assessment: dict | None = None,
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
        "chapter_assessment": assessment,
    }
    keywords = "、".join(profile["keywords"])
    excluded = "、".join(profile["excluded_topics"]) or "无"
    system = (
        f"你是尊重边界的中文口述史采访者。当前唯一采访章节是“{profile['title']}”。"
        f"本章关键词：{keywords}。本章采访目标：{profile['interview_goal']}。"
        f"越界主题：{excluded}。根据 chapter_assessment 和已知记忆回应用户最新一条消息。"
        "如果script_action为regenerate_script，应优先回应用户的重写要求，不要重复之前的采访问题。"
        "script_updated为true才可以告知本章已重新生成，并请用户查看或提出调整；"
        "为false说明资料仍不足，应具体解释缺少什么，不能谎称生成成功。"
        "无论用户是否要求重写，只要ready_for_script为false，这就是正常采访而不是错误："
        "先承接用户刚讲的内容，再自然说明还需要哪一点细节才能写成本章剧本，"
        "并据reason和missing_topics只提出一个具体问题；不要展示错误码、校验或故障措辞。"
        "用户明确不愿继续时尊重其意愿，不强行追问。"
        "有重要缺口时，只问一个本章内最有价值的问题；用户提到越界内容时可以简短承接，"
        "但不得继续展开其他章节。不得臆造事实、重复 answered_questions 中的问题、"
        "暗示所谓正确答案，或施压回答隐私。用户不提供的信息要尊重，不反复追问。"
        "当本章信息已经齐全、用户希望暂告一段落或没有值得追问的新问题时，"
        "请根据已讲述的具体内容，简短回应并自然收束，允许用户以后继续补充。"
        "此时 next_question 仍须填写这段给用户的回应，intent 使用 meaning，"
        "不必强行写成问句，不得输出空对象、空字符串、null 或仅一个符号。"
        "只输出包含两个必填字段的 JSON 对象。next_question 为 2 至 240 字的中文回应；"
        "intent 只能从 timeline、person、place、event、consequence、feeling、meaning "
        "中选择一个值，不得把多个值用竖线拼接。格式："
        '{"next_question":"这里填写本章的追问或回应正文","intent":"meaning"}。'
    )
    allowed_intents = {
        "timeline",
        "person",
        "place",
        "event",
        "consequence",
        "feeling",
        "meaning",
    }
    for attempt in range(2):
        retry_hint = (
            "\n上次返回未通过格式校验。请重新阅读上下文，严格输出必填的 next_question "
            "和 intent。如果已无信息缺口，请给出非空的自然收束回应，不得返回 {}。"
            if attempt else ""
        )
        try:
            result = client.chat_json(system + retry_hint, json.dumps(context, ensure_ascii=False))
        except json.JSONDecodeError:
            continue
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError(
                status.HTTP_502_BAD_GATEWAY,
                ErrorCode.INTERVIEW_LLM_REQUEST_FAILED,
            ) from exc
        if not isinstance(result, dict):
            continue
        question = result.get("next_question")
        intent = result.get("intent")
        if not isinstance(question, str) or not isinstance(intent, str):
            continue
        question = question.strip().strip('"“” ')
        intent = intent.strip()
        if (
            2 <= len(question) <= 240
            and any(char.isalnum() for char in question)
            and intent in allowed_intents
            and question not in context["answered_questions"]
        ):
            return {"question": question, "intent": intent}
    raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.INTERVIEW_LLM_RESPONSE_INVALID)


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
    from lifereel_api.modules.interview.voice_service import assert_no_call, lock_session

    lock_session(db, tenant_id, session_id)
    assert_no_call(db, tenant_id, session_id)
    session = get_session(db, tenant_id, session_id)
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
    from lifereel_api.modules.interview.voice_service import assert_no_call, lock_session

    lock_session(db, tenant_id, session_id)
    assert_no_call(db, tenant_id, session_id)
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
    require_memory_input(answer_text)
    round_.answer_text = answer_text
    round_.source_asset_id = source_asset_id
    round_.answered_at = datetime.now(UTC)
    round_.transcript_status = "done"
    db.commit()
    db.refresh(round_)
    return round_


@track_usage("question")
def suggest_next_question(
    db: Session,
    tenant_id: UUID,
    session_id: UUID,
    assessment: dict | None = None,
) -> dict[str, str]:
    from lifereel_api.modules.interview.voice_service import assert_no_call

    assert_no_call(db, tenant_id, session_id)
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
            llm_result = _llm_follow_up(db, tenant_id, session, answered, assessment)
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
        llm_result = _llm_follow_up(db, tenant_id, session, answered, assessment)
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
    if assessment and assessment.get("script_action") == "regenerate_script":
        question = (
            "本章剧本已重新生成，您可以查看后继续提出调整。"
            if assessment.get("script_updated")
            else "现有信息还不足以成稿，请补充一件本章的具体往事。"
        )
        intent = "meaning"
    elif declined:
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

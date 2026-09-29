from uuid import UUID, uuid5

from sqlalchemy import select

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.interview.models import InterviewSession, InterviewVoiceCall
from lifereel_api.modules.memory import service
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.modules.memory.schemas import MemoryCompileRequest

CALLERS = {"interview", "worker-interview"}


def compile_memory(db, tenant, data):
    created, updated, claims = service.compile_memories(
        db, tenant, MemoryCompileRequest.model_validate(data)
    )
    return {"created": created, "updated": updated, "claim_ids": [str(c.id) for c in claims]}


def voice_claim(db, tenant, data):
    call = db.scalar(
        select(InterviewVoiceCall).where(
            InterviewVoiceCall.id == UUID(data["call_id"]),
            InterviewVoiceCall.tenant_id == tenant,
        )
    )
    if call is None or call.status not in {"connecting", "active", "closing"}:
        raise ApiError(409, ErrorCode.VOICE_CALL_EXPIRED)
    session = db.scalar(
        select(InterviewSession).where(
            InterviewSession.id == call.session_id,
            InterviewSession.tenant_id == tenant,
        )
    )
    claim_id = uuid5(call.id, data["key"])
    if db.get(MemoryClaim, claim_id):
        return {"created": False}
    text = data["text"]
    if not isinstance(text, str) or len(text) > 32000:
        raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)
    claim, kind, confidence, provider, model = service._extract_claim(
        text,
        "realtime_voice",
        question=data.get("question", ""),
    )
    db.add(
        MemoryClaim(
            id=claim_id,
            tenant_id=tenant,
            subject_id=session.subject_id,
            interview_session_id=session.id,
            chapter_id=session.chapter_id,
            source_round_id=None,
            source_observation_id=None,
            source_quote="",
            claim_text=claim,
            claim_type=kind,
            confidence=confidence,
            review_status="unreviewed",
            extraction_provider=provider,
            extraction_model=model,
        )
    )
    return {"created": True}


OPERATIONS = {
    "memory.compile": (CALLERS, compile_memory),
    "memory.voice-claim": (CALLERS, voice_claim),
}

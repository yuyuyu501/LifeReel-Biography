from uuid import UUID

from sqlalchemy import select

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.interview.models import Chapter, InterviewRound
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.modules.script import service
from lifereel_api.modules.script.schemas import ScriptGenerateRequest

CALLERS = {"interview", "worker-interview"}


def owned_rows(db, model, tenant, ids):
    identities = [UUID(value) for value in ids]
    rows = list(
        db.scalars(select(model).where(model.tenant_id == tenant, model.id.in_(identities)))
    )
    lookup = {row.id: row for row in rows}
    if set(identities) != set(lookup):
        raise ApiError(404, ErrorCode.REQUEST_FAILED)
    return [lookup[key] for key in identities]


def assess(db, tenant, data):
    from lifereel_api.modules.script.assessment import assess_chapter

    claims = owned_rows(db, MemoryClaim, tenant, data["claim_ids"])
    rounds = owned_rows(db, InterviewRound, tenant, data["round_ids"])
    chapters = (
        owned_rows(db, Chapter, tenant, [data["chapter_id"]]) if data.get("chapter_id") else []
    )
    return assess_chapter(db, tenant, claims, rounds, chapters[0] if chapters else None)


def generate(db, tenant, data):
    request = ScriptGenerateRequest.model_validate(data["request"])
    from lifereel_api.modules.script.freshness import is_current, revision_key

    def check():
        return True

    if data.get("freshness"):
        import redis

        from lifereel_api.core.config import get_settings
        from lifereel_api.modules.interview.models import InterviewSession, InterviewVoiceCall

        guard = data["freshness"]
        voice = db.scalar(
            select(InterviewVoiceCall)
            .join(
                InterviewSession,
                InterviewSession.id == InterviewVoiceCall.session_id,
            )
            .where(
                InterviewVoiceCall.tenant_id == tenant,
                InterviewVoiceCall.id == UUID(guard["call_id"]),
                InterviewSession.subject_id == request.subject_id,
            )
        )
        if voice is None:
            raise ApiError(403, ErrorCode.AUTH_READ_ONLY)
        store = redis.from_url(get_settings().redis_url, socket_timeout=5, decode_responses=True)
        key = revision_key(tenant, voice.id)

        def check():
            return store.get(key) == str(guard["revision"])

    token = is_current.set(check)
    try:
        project, _, _ = service.generate_draft(
            db, tenant, request, update_brief=data.get("update_brief")
        )
        return {"project_id": str(project.id)}
    finally:
        is_current.reset(token)


def reserve(db, tenant, data):
    return {
        "key": service.reserve_interview_update(
            db, tenant, ScriptGenerateRequest.model_validate(data)
        )
    }


OPERATIONS = {
    "script.assess": (CALLERS, assess),
    "script.generate": (CALLERS, generate),
    "script.reserve": (CALLERS, reserve),
}

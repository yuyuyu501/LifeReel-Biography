"""Live voice updates. Raw utterances exist only in this connection's bounded RAM queue."""

import asyncio
import logging
from uuid import UUID, uuid5

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing.usage import track_usage
from lifereel_api.modules.interview import voice_service
from lifereel_api.modules.interview.models import Chapter
from lifereel_api.modules.memory import service as memory
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.modules.memory.schemas import MemoryCompileRequest
from lifereel_api.modules.orchestration.intent import classify_turn
from lifereel_api.modules.orchestration.service import _assess_chapter
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.modules.script import service as scripts
from lifereel_api.modules.script.schemas import ScriptGenerateRequest

logger = logging.getLogger(__name__)


@track_usage("interview")
def _process(db, tenant_id, update_id, call_id, utterances):
    call = voice_service.get_call(db, tenant_id, call_id)
    if call.status not in voice_service.ACTIVE:
        raise ApiError(409, ErrorCode.VOICE_CALL_EXPIRED)
    session = voice_service.lock_session(db, tenant_id, call.session_id)
    subject_id, session_id, chapter_id = session.subject_id, session.id, session.chapter_id
    db.commit()
    instructions = []
    changed = False
    for key, text, question in utterances:
        intent = classify_turn(text)
        if intent["instructions"]:
            instructions.append(intent["instructions"])
        if not intent["has_new_facts"]:
            continue
        claim_id = uuid5(call_id, key)
        if db.get(MemoryClaim, claim_id):
            continue
        claim, kind, confidence, provider, model = memory._extract_claim(
            text, "realtime_voice", question=question,
        )
        db.add(MemoryClaim(
            id=claim_id, tenant_id=tenant_id, subject_id=subject_id,
            interview_session_id=session_id, chapter_id=chapter_id,
            source_round_id=None, source_observation_id=None, source_quote="",
            claim_text=claim, claim_type=kind, confidence=confidence,
            review_status="unreviewed", extraction_provider=provider, extraction_model=model,
        ))
        db.commit()
        changed = True
    if not changed and not instructions:
        return {"memory_updated": False, "script_updated": False}
    # Reuse the existing graph/biography compiler with only derived voice claims persisted.
    memory.compile_memories(db, tenant_id, MemoryCompileRequest(interview_session_id=session_id))
    claims = list(db.scalars(select(MemoryClaim).where(
        MemoryClaim.tenant_id == tenant_id, MemoryClaim.subject_id == subject_id,
        MemoryClaim.chapter_id == chapter_id,
        MemoryClaim.review_status.not_in(["disputed", "private"]),
    ).order_by(MemoryClaim.created_at)))
    chapter = db.get(Chapter, chapter_id) if chapter_id else None
    assessment = _assess_chapter(db, tenant_id, claims, [], chapter)
    updated = False
    if claims and assessment["ready_for_script"]:
        scripts.generate_draft(db, tenant_id, ScriptGenerateRequest(
            subject_id=subject_id, chapter_id=chapter_id, idempotency_key=update_id,
            mode="single_chapter", audience="family",
        ), update_brief={
            "script_instructions": "\n".join(instructions),
            "update_mode": "replace_current_chapter",
            "missing_topics": assessment["missing_topics"],
        })
        updated = True
    return {"memory_updated": changed, "script_updated": updated}


def process(call_id: UUID, tenant_id: UUID, utterances: list[tuple[str, str, str]]):
    # A single consumer owns this call. No transcript is put in a durable job or workflow.
    with SessionLocal() as db, execution_lock(db, call_id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.RESOURCE_BUSY)
        return _process(db, tenant_id, uuid5(call_id, utterances[-1][0]), call_id, utterances)


class LiveUpdates:
    def __init__(self, tenant_id, call_id, send):
        self.tenant_id, self.call_id, self.send = tenant_id, call_id, send
        self.queue = asyncio.Queue(maxsize=32)
        self.seen = set()
        self.failed = False
        self.task = asyncio.create_task(self._consume())

    def submit(self, key, text, question=""):
        if not text.strip() or key in self.seen:
            return
        if len(text) > 12000 or len(key) > 200:
            raise ApiError(502, ErrorCode.VOICE_PROTOCOL_INVALID)
        if len(self.seen) >= 400 or self.queue.full():
            raise ApiError(409, ErrorCode.VOICE_LIMIT_REACHED)
        self.seen.add(key)
        self.queue.put_nowait((key, text.strip(), question[:2000]))

    async def _consume(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            # Process utterances in order while the speech socket continues to listen/reply.
            batch = [item]
            await self.send({"type": "update.started"})
            try:
                result = await run_in_threadpool(process, self.call_id, self.tenant_id, batch)
                await self.send({"type": "update.done", **result})
            except Exception as exc:
                self.failed = True
                code = exc.code.value if isinstance(exc, ApiError) else "WORKER_ERROR"
                logger.warning("Live voice update failed: %s", code)
                await self.send({"type": "update.failed", "code": code})
            finally:
                # Do not retain processed utterances while waiting for the next turn.
                batch.clear()
                item = None

    async def close(self):
        async def drain():
            await self.queue.put(None)
            await self.task

        draining = asyncio.create_task(drain())
        while not draining.done():
            done, _ = await asyncio.wait([draining], timeout=10)
            if not done:
                await run_in_threadpool(voice_service.touch, self.tenant_id, self.call_id)
        await draining
        self.seen.clear()

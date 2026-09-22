"""Live voice updates. Raw utterances exist only in this connection's bounded RAM queue."""

import asyncio
import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID, uuid5

from starlette.concurrency import run_in_threadpool

from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing.usage import track_usage
from lifereel_api.modules.interview import voice_service
from lifereel_api.modules.interview.models import Chapter
from lifereel_api.modules.memory import service as memory
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.modules.orchestration.intent import classify_turn
from lifereel_api.modules.orchestration.skills import MemorySkill, ScriptSkill
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.modules.script.freshness import is_current
from lifereel_api.modules.script.schemas import ScriptGenerateRequest
from lifereel_api.providers.realtime_voice import tool_result_event

logger = logging.getLogger(__name__)
_instructions = ContextVar("voice_skill_instructions", default=None)
_script_pending = ContextVar("voice_script_pending", default=False)


@track_usage("interview")
def _process(db, tenant_id, update_id, call_id, utterances):
    call = voice_service.get_call(db, tenant_id, call_id)
    if call.status not in voice_service.ACTIVE:
        raise ApiError(409, ErrorCode.VOICE_CALL_EXPIRED)
    session = voice_service.lock_session(db, tenant_id, call.session_id)
    subject_id, session_id, chapter_id = session.subject_id, session.id, session.chapter_id
    db.commit()
    retained = _instructions.get()
    instructions = retained if retained is not None else []
    changed = False
    requested = False
    for key, text, question in utterances:
        intent = classify_turn(text)
        if intent["instructions"]:
            requested = True
            if intent["instructions"] not in instructions:
                if sum(map(len, instructions)) + len(intent["instructions"]) > 8000:
                    raise ApiError(409, ErrorCode.VOICE_LIMIT_REACHED)
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
    if not changed and not requested and not _script_pending.get():
        return {"memory_updated": False, "script_updated": False}
    # Reuse the existing graph/biography compiler with only derived voice claims persisted.
    if changed:
        MemorySkill.compile(db, tenant_id, session_id)
    claims = MemorySkill.chapter_claims(db, tenant_id, subject_id, chapter_id)
    chapter = db.get(Chapter, chapter_id) if chapter_id else None
    assessment = ScriptSkill.assess(db, tenant_id, claims, [], chapter)
    updated = False
    if claims and assessment["ready_for_script"]:
        if not is_current.get()():
            return {"memory_updated": changed, "script_updated": False, "pending": True}
        ScriptSkill.generate(db, tenant_id, ScriptGenerateRequest(
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
        try:
            return _process(db, tenant_id, uuid5(call_id, utterances[-1][0]), call_id, utterances)
        except ApiError as exc:
            if exc.code == ErrorCode.SCRIPT_EDIT_CONFLICT and not is_current.get()():
                return {"memory_updated": True, "script_updated": False, "pending": True}
            raise


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    valid: bool
    revision: int


@dataclass(frozen=True)
class ToolBatch:
    calls: tuple[ToolCall, ...]


class LiveUpdates:
    def __init__(self, tenant_id, call_id, send, send_provider=None):
        self.tenant_id, self.call_id, self.send = tenant_id, call_id, send
        self.queue = asyncio.Queue(maxsize=32)
        self.seen = set()
        self.failed = False
        self.send_provider = send_provider
        self.revision = 0
        self.completed_revision = 0
        self.processed_revision = 0
        self.failed_revisions = []
        self.result = {}
        self.tool_calls = {}
        self.tool_results = {}
        self.closing = False
        self.instructions = []
        self.task = asyncio.create_task(self._consume())

    def submit(self, key, text, question=""):
        if self.closing:
            raise ApiError(409, ErrorCode.VOICE_CALL_EXPIRED)
        if not text.strip() or key in self.seen:
            return
        if len(text) > 12000 or len(key) > 200:
            raise ApiError(502, ErrorCode.VOICE_PROTOCOL_INVALID)
        if len(self.seen) >= 400 or self.queue.full():
            raise ApiError(409, ErrorCode.VOICE_LIMIT_REACHED)
        self.seen.add(key)
        self.revision += 1
        self.queue.put_nowait((key, text.strip(), question[:2000]))

    async def submit_tools(self, event):
        """Validate provider calls without accepting model-supplied identity or facts."""
        items = event.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 8:
            raise ApiError(502, ErrorCode.VOICE_PROTOCOL_INVALID)
        additions = {}
        calls = {}
        for item in items:
            if not isinstance(item, dict):
                raise ApiError(502, ErrorCode.VOICE_PROTOCOL_INVALID)
            call_id, name, arguments = (item.get(k) for k in ("call_id", "name", "arguments"))
            if (not isinstance(call_id, str) or not 1 <= len(call_id) <= 200
                    or not isinstance(name, str) or len(name) > 80
                    or not isinstance(arguments, str) or len(arguments) > 2000):
                raise ApiError(502, ErrorCode.VOICE_PROTOCOL_INVALID)
            signature = (name, arguments)
            previous = self.tool_calls.get(call_id) or additions.get(call_id)
            if previous:
                if previous[:2] != signature:
                    raise ApiError(502, ErrorCode.VOICE_PROTOCOL_INVALID)
            try:
                valid = json.loads(arguments) == {} and name in {"sync_memory", "update_script"}
            except (ValueError, TypeError):
                valid = False
            revision = previous[2] if previous else self.revision
            calls[call_id] = ToolCall(call_id, name, valid, revision)
            if not previous:
                additions[call_id] = (*signature, revision)
        if not additions:
            if all(call_id in self.tool_results for call_id in calls) and self.send_provider:
                await self.send_provider(tool_result_event([
                    (call_id, self.tool_results[call_id]) for call_id in calls
                ]))
            return
        if self.closing or len(self.tool_calls) + len(additions) > 128 or self.queue.full():
            raise ApiError(409, ErrorCode.VOICE_LIMIT_REACHED)
        self.tool_calls.update(additions)
        self.queue.put_nowait(ToolBatch(tuple(calls.values())))

    def _tool_result(self, item):
        if item.call_id in self.tool_results:
            return self.tool_results[item.call_id]
        if not item.valid:
            result = {"status": "rejected", "code": "INVALID_SKILL_ARGUMENTS"}
        elif not item.revision:
            result = {"status": "pending", "code": "AWAITING_COMPLETED_UTTERANCE"}
        elif (self.completed_revision < item.revision
              or any(revision <= item.revision for revision in self.failed_revisions)):
            result = {"status": "failed", "code": "UPDATE_FAILED"}
        elif self.result.get("pending") or self.revision > self.completed_revision:
            result = {"status": "pending", "code": "NEWER_UTTERANCE_PENDING"}
        else:
            updated = self.result.get(
                "memory_updated" if item.name == "sync_memory" else "script_updated", False,
            )
            result = {"status": "completed" if updated else "unchanged",
                      "processed_revision": self.completed_revision}
        self.tool_results[item.call_id] = result
        return result

    async def _consume(self):
        pending = None
        while True:
            item = pending if pending is not None else await self.queue.get()
            pending = None
            if item is None:
                return
            if isinstance(item, ToolBatch):
                try:
                    results = [(call.call_id, self._tool_result(call)) for call in item.calls]
                    if self.send_provider:
                        await self.send_provider(tool_result_event(results))
                except Exception:
                    self.failed = True
                    logger.warning("Voice skill result delivery failed")
                    await self.send({"type": "update.failed", "code": "VOICE_CONNECTION_FAILED"})
                continue
            # Coalesce a short burst; tool requests are ordered barriers. Raw text
            # remains only in this bounded queue, never in a durable job payload.
            batch = [item]
            stopping = False
            while len(batch) < 8:
                try:
                    following = await asyncio.wait_for(self.queue.get(), timeout=0.25)
                except TimeoutError:
                    break
                if following is None:
                    stopping = True
                    break
                if isinstance(following, ToolBatch):
                    pending = following
                    break
                batch.append(following)
            revision = self.processed_revision + len(batch)
            self.processed_revision = revision
            await self.send({"type": "update.started"})
            guard = is_current.set(lambda revision=revision: self.revision == revision)
            instructions_token = _instructions.set(self.instructions)
            pending_token = _script_pending.set(self.result.get("pending", False))
            try:
                result = await run_in_threadpool(process, self.call_id, self.tenant_id, batch)
                self.result = result
                self.result["pending"] = result.get("pending", False) or self.revision > revision
                self.completed_revision = revision
                await self.send({"type": "update.done", **self.result})
            except Exception as exc:
                self.failed = True
                self.failed_revisions.append(revision)
                code = exc.code.value if isinstance(exc, ApiError) else "WORKER_ERROR"
                logger.warning("Live voice update failed: %s", code)
                await self.send({"type": "update.failed", "code": code})
            finally:
                is_current.reset(guard)
                _instructions.reset(instructions_token)
                _script_pending.reset(pending_token)
                # Do not retain processed utterances while waiting for the next turn.
                batch.clear()
                item = None
            if stopping:
                return

    async def close(self):
        self.closing = True

        async def drain():
            putting = asyncio.create_task(self.queue.put(None))
            try:
                await asyncio.wait([putting, self.task], return_when=asyncio.FIRST_COMPLETED)
                if not putting.done():
                    putting.cancel()
                await asyncio.gather(putting, return_exceptions=True)
            finally:
                if not putting.done():
                    putting.cancel()
            await self.task

        draining = asyncio.create_task(drain())
        while not draining.done():
            done, _ = await asyncio.wait([draining], timeout=10)
            if not done:
                await run_in_threadpool(voice_service.touch, self.tenant_id, self.call_id)
        try:
            await draining
        finally:
            while not self.queue.empty():
                self.queue.get_nowait()
            self.seen.clear()
            self.tool_calls.clear()
            self.tool_results.clear()
            self.instructions.clear()

import asyncio
import threading
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_interview_voice import ORIGIN, receive_until, voice

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.interview import voice_service, voice_updates
from lifereel_api.modules.interview.models import InterviewVoiceCall
from lifereel_api.modules.memory import service as memory
from lifereel_api.modules.memory.models import MemoryClaim

__all__ = ["voice"]


@pytest.mark.asyncio
async def test_sequential_updates_dedupe_and_clear_pending_text(monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls, events = [], []

    def process(_call, _tenant, utterances):
        calls.extend(item[0] for item in utterances)
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
        return {"memory_updated": True, "script_updated": True}

    async def send(event):
        events.append(event)

    monkeypatch.setattr(voice_updates, "process", process)
    updates = voice_updates.LiveUpdates(uuid4(), uuid4(), send)
    updates.submit("one", "第一轮", "问题一")
    try:
        assert await asyncio.to_thread(started.wait, 5)
        updates.submit("one", "重复第一轮")
        updates.submit("two", "第二轮", "问题二")
        assert calls == ["one"]
    finally:
        release.set()
        await updates.close()
    assert calls == ["one", "two"]
    assert [e["type"] for e in events] == [
        "update.started", "update.done", "update.started", "update.done",
    ]
    assert updates.queue.empty() and updates.seen == set()


@pytest.mark.asyncio
async def test_failure_is_reported_without_retry_and_next_utterance_can_continue(monkeypatch):
    calls, events = [], []

    def process(_call, _tenant, utterances):
        calls.append(utterances[0][0])
        if calls[-1] == "one":
            raise RuntimeError("private transcript must not escape")
        return {"memory_updated": True, "script_updated": False}

    async def send(event):
        events.append(event)

    monkeypatch.setattr(voice_updates, "process", process)
    updates = voice_updates.LiveUpdates(uuid4(), uuid4(), send)
    updates.submit("one", "临时原文一")
    updates.submit("one", "临时原文一")
    updates.submit("two", "临时原文二")
    await updates.close()
    assert calls == ["one", "two"]
    assert updates.failed
    assert {"type": "update.failed", "code": "WORKER_ERROR"} in events
    assert "private transcript" not in str(events)
    assert events[-1]["type"] == "update.done"


def test_voice_rewrite_uses_existing_knowledge_without_creating_source_text(
    client, voice, monkeypatch,
):
    _, call = voice
    tenant, call_id = get_settings().default_tenant_id, UUID(call["id"])
    voice_service.attach(tenant, None, call_id)
    voice_updates.process(call_id, tenant, [("fact", "我和母亲在家乡生活。", "")])
    briefs = []
    original = voice_updates.scripts.generate_draft

    def generate(db, tenant, payload, update_brief):
        briefs.append(update_brief)
        return original(db, tenant, payload, update_brief)

    monkeypatch.setattr(voice_updates.scripts, "generate_draft", generate)
    result = voice_updates.process(call_id, tenant, [("rewrite", "重写剧本，改成第一人称。", "")])
    assert result == {"memory_updated": False, "script_updated": True}
    assert briefs[0]["script_instructions"] == "重写剧本，改成第一人称。"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MemoryClaim)) == 1
        assert db.get(InterviewVoiceCall, call_id).messages == []


def test_source_question_is_transient_and_cross_tenant_updates_are_denied(
    client, voice, monkeypatch,
):
    _, call = voice
    tenant, call_id = get_settings().default_tenant_id, UUID(call["id"])
    voice_service.attach(tenant, None, call_id)
    seen = []

    def extract(text, source_kind, *, question):
        seen.append((text, source_kind, question))
        return "1965年入学。", "event", 0.9, "test", None

    monkeypatch.setattr(memory, "_extract_claim", extract)
    with pytest.raises(ApiError) as failure:
        voice_updates.process(call_id, uuid4(), [("year", "1965年。", "哪年入学？")])
    assert failure.value.code == ErrorCode.VOICE_CALL_NOT_FOUND
    assert seen == []
    voice_updates.process(call_id, tenant, [("year", "1965年。", "哪年入学？")])
    assert seen == [("1965年。", "realtime_voice", "哪年入学？")]
    with SessionLocal() as db:
        claim = db.scalar(select(MemoryClaim))
        assert claim.source_quote == "" and claim.source_round_id is None


def test_slow_updates_do_not_block_audio_or_control_messages(client, voice, monkeypatch):
    _, call = voice
    started, release = threading.Event(), threading.Event()

    def process(*_):
        started.set()
        assert release.wait(5)
        return {"memory_updated": True, "script_updated": True}

    monkeypatch.setattr(voice_updates, "process", process)
    with client.websocket_connect(f"/v1/interview-voice/{call['id']}/stream", headers=ORIGIN) as ws:
        receive_until(ws, "ready")
        ws.send_bytes(bytes(640))
        try:
            assert started.wait(5)
            ws.send_json({"type": "ping"})
            _, events = receive_until(ws, "pong")
            assert any(e["type"] == "audio" for e in events)
        finally:
            release.set()
        receive_until(ws, "update.done")
        ws.send_json({"type": "end"})
        result, _ = receive_until(ws, "ended")
        assert result["call"]["messages"] == []

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from test_interview_voice import ORIGIN, receive_until, voice

from lifereel_api.core.errors import ApiError
from lifereel_api.modules.interview import voice_updates
from lifereel_api.modules.script.freshness import is_current
from lifereel_api.providers import realtime_voice

__all__ = ["voice"]


def fc(call_id, name="sync_memory", arguments="{}"):
    return {"type": "response.function_call_arguments.done", "items": [
        {"type": "function_call", "call_id": call_id, "name": name, "arguments": arguments},
    ]}


def result(event):
    assert event["type"] == "conversation.item.create"
    assert event["items"][0]["role"] == "tool"
    assert event["items"][0]["content"][0]["type"] == "input_text"
    return json.loads(event["items"][0]["content"][0]["text"])


def test_official_flat_function_schema_has_no_identity_or_fact_parameters():
    tools = realtime_voice.session_event("call", "interview")["session"]["tools"]
    assert {t["name"] for t in tools} == {"sync_memory", "update_script"}
    assert all(t["type"] == "function" and t["parameters"]["properties"] == {} for t in tools)


@pytest.mark.asyncio
async def test_bursts_and_duplicate_tool_calls_share_one_update(monkeypatch):
    calls, replies, events = [], [], []

    def process(call, tenant, utterances):
        calls.append([u[0] for u in utterances])
        return {"memory_updated": True, "script_updated": True}

    async def send(event):
        events.append(event)

    async def upstream(event):
        replies.append(event)

    monkeypatch.setattr(voice_updates, "process", process)
    updates = voice_updates.LiveUpdates(uuid4(), uuid4(), send, upstream)
    updates.submit("one", "1970年过桥")
    updates.submit("two", "更正：不是1970年，是1971年")
    await updates.submit_tools(fc("memory"))
    await updates.submit_tools(fc("memory"))
    await updates.submit_tools(fc("script", "update_script"))
    await updates.close()
    assert calls == [["one", "two"]]
    assert [r["items"][0]["call_id"] for r in replies] == ["memory", "script"]
    assert all(result(r)["status"] == "completed" for r in replies)
    assert len([e for e in events if e["type"] == "update.done"]) == 1
    assert updates.queue.empty() and not updates.instructions


@pytest.mark.asyncio
async def test_tools_cannot_inject_facts_or_identity_and_early_call_is_pending():
    replies = []

    async def send(_):
        pass

    async def upstream(event):
        replies.append(event)

    updates = voice_updates.LiveUpdates(uuid4(), uuid4(), send, upstream)
    await updates.submit_tools(fc("early"))
    await updates.submit_tools(fc("scope", arguments='{"subject_id":"someone-else"}'))
    await updates.submit_tools(fc("unknown", "delete_memories"))
    await updates.submit_tools(fc("bad-json", arguments="["))
    with pytest.raises(ApiError):
        await updates.submit_tools(fc("early", "update_script"))
    await updates.close()
    assert [result(r)["status"] for r in replies] == ["pending", "rejected", "rejected", "rejected"]


@pytest.mark.asyncio
async def test_multiple_official_items_are_returned_together_and_replayed_without_work(monkeypatch):
    replies, calls = [], []
    delivered = asyncio.Event()

    def process(*_):
        calls.append(1)
        return {"memory_updated": True, "script_updated": True}

    async def send(_):
        pass

    async def upstream(event):
        replies.append(event)
        delivered.set()

    monkeypatch.setattr(voice_updates, "process", process)
    updates = voice_updates.LiveUpdates(uuid4(), uuid4(), send, upstream)
    updates.submit("one", "童年生活")
    event = fc("memory")
    event["items"].extend(fc("script", "update_script")["items"])
    await updates.submit_tools(event)
    await asyncio.wait_for(delivered.wait(), 5)
    await updates.submit_tools(event)
    await updates.close()
    assert calls == [1]
    assert len(replies) == 2
    assert replies[0]["items"] == replies[1]["items"]
    assert [item["call_id"] for item in replies[0]["items"]] == ["memory", "script"]


@pytest.mark.asyncio
async def test_invalid_batch_is_rejected_atomically():
    async def send(_):
        pass

    updates = voice_updates.LiveUpdates(uuid4(), uuid4(), send)
    event = fc("valid")
    event["items"].append({"call_id": None})
    with pytest.raises(ApiError):
        await updates.submit_tools(event)
    assert updates.tool_calls == {} and updates.queue.empty()
    await updates.close()


@pytest.mark.asyncio
async def test_new_utterance_invalidates_inflight_draft_without_blocking_queue(monkeypatch):
    started, release = threading.Event(), threading.Event()
    freshness, events = [], []

    def process(call, tenant, utterances):
        if utterances[0][0] == "one":
            started.set()
            assert release.wait(5)
        current = is_current.get()()
        freshness.append(current)
        return {"memory_updated": True, "script_updated": current}

    async def send(event):
        events.append(event)

    monkeypatch.setattr(voice_updates, "process", process)
    updates = voice_updates.LiveUpdates(uuid4(), uuid4(), send)
    updates.submit("one", "旧年份")
    try:
        assert await asyncio.to_thread(started.wait, 5)
        updates.submit("two", "明确更正年份")
    finally:
        release.set()
        await updates.close()
    assert freshness == [False, True]
    done = [e for e in events if e["type"] == "update.done"]
    assert done[0]["pending"] and not done[0]["script_updated"]
    assert not done[1]["pending"] and done[1]["script_updated"]


@pytest.mark.asyncio
async def test_failed_update_is_not_reported_as_success_by_tool(monkeypatch):
    replies = []

    def process(*_):
        raise RuntimeError("private-source")

    async def send(_):
        pass

    async def upstream(event):
        replies.append(event)

    monkeypatch.setattr(voice_updates, "process", process)
    updates = voice_updates.LiveUpdates(uuid4(), uuid4(), send, upstream)
    updates.submit("one", "private-source")
    await updates.submit_tools(fc("memory"))
    await updates.close()
    assert result(replies[0])["status"] == "failed"
    assert "private-source" not in str(replies)


def test_websocket_dispatches_official_fc_and_returns_real_skill_status(client, voice, monkeypatch):
    _, call = voice
    replies = []

    class Connection(realtime_voice.MockConnection):
        async def send(self, event):
            await super().send(event)
            if event["type"] == "input_audio_buffer.append" and self.turn == 1:
                await self.events.put(fc("memory-call"))
            elif event["type"] == "conversation.item.create":
                replies.append(event)
                await self.events.put({"type": "response.output_text.done",
                                       "response_id": "tool-reply", "text": "整理完成"})

    @asynccontextmanager
    async def connect():
        yield Connection()

    monkeypatch.setattr(realtime_voice, "open_connection", connect)
    with client.websocket_connect(f"/v1/interview-voice/{call['id']}/stream", headers=ORIGIN) as ws:
        receive_until(ws, "ready")
        ws.send_bytes(bytes(640))
        for _ in range(30):
            event = ws.receive_json()
            if event.get("id") == "tool-reply":
                break
        else:
            pytest.fail("Missing function result response")
        assert replies[0]["items"][0]["call_id"] == "memory-call"
        assert result(replies[0])["status"] == "completed"
        ws.send_json({"type": "end"})
        receive_until(ws, "ended")

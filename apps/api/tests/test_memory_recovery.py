import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from lifereel_api.core.errors import ApiError
from lifereel_api.modules.memory import recovery
from lifereel_api.modules.memory.structured import MemoryClient
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


def test_claim_correction_is_specific_and_does_not_log_private_content(monkeypatch, caplog):
    calls = []

    def response(self, system, user):
        calls.append(system)
        if len(calls) == 1:
            return {"claim_text": "PRIVATE-SOURCE", "claim_type": "values", "confidence": 0.9}
        assert "claim_type: literal_error" in system
        assert "JSON Schema" in system
        return {"claim_text": "PRIVATE-SOURCE", "claim_type": "recollection", "confidence": 0.9}

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", response)
    client = MemoryClient("https://test/v1", "key", "test", stage="claim")
    assert client.chat_json("整理", "原文")["claim_type"] == "recollection"
    assert len(calls) == 2
    assert "claim_type" in caplog.text
    assert "PRIVATE-SOURCE" not in caplog.text


@pytest.mark.parametrize(
    "invalid", [[], {}, {"claim_text": "x", "claim_type": "event", "confidence": "0.8"}]
)
def test_invalid_response_stops_after_one_correction(monkeypatch, invalid):
    calls = []
    monkeypatch.setattr(
        OpenAICompatibleClient, "chat_json", lambda *args: calls.append(1) or invalid
    )
    with pytest.raises(ApiError) as caught:
        MemoryClient("https://test", "key", "test", stage="claim").chat_json("", "")
    assert caught.value.code.value == "MEMORY_LLM_RESPONSE_INVALID"
    assert caught.value.diagnostic["attempt"] == 2
    assert len(calls) == 2


def test_unknown_graph_source_is_repaired_not_silently_dropped(monkeypatch):
    calls = []
    source_id = str(uuid4())

    def respond(self, system, user):
        calls.append(system)
        return {
            "entities": [
                {
                    "name": "父亲",
                    "normalized_name": "父亲",
                    "entity_type": "person",
                    "relationship": "父亲",
                    "source_claim_ids": ["invented" if len(calls) == 1 else source_id],
                }
            ],
            "timeline": [],
            "conflicts": [],
        }

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", respond)
    result = MemoryClient("https://test", "key", "test", stage="graph").chat_json(
        "", json.dumps({"claims": [{"claim_id": source_id}]})
    )
    assert result["entities"][0]["source_claim_ids"] == [source_id]
    assert "unknown_source" in calls[1]


@pytest.mark.parametrize(
    "failure, expected",
    [
        (httpx.ConnectError("offline"), 2),
        (httpx.ReadTimeout("uncertain receipt"), 1),
    ],
)
def test_transport_retry_is_bounded_and_avoids_uncertain_calls(monkeypatch, failure, expected):
    calls = []

    def fail(*args):
        calls.append(1)
        raise failure

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", fail)
    monkeypatch.setattr("lifereel_api.modules.memory.structured.time.sleep", lambda _: None)
    with pytest.raises(ApiError):
        MemoryClient("https://test", "key", "test", stage="claim").chat_json("", "")
    assert len(calls) == expected


def test_retry_policy_preserves_legacy_repair_but_limits_new_attempts():
    w = SimpleNamespace(script_brief={})
    assert recovery.allowed(w)
    w.script_brief = {"memory_recovery": {"version": recovery.VERSION, "runs": 3}}
    assert not recovery.allowed(w)
    w.script_brief["memory_recovery"].update(runs=1, budget_exhausted=True)
    assert not recovery.allowed(w)
    w.script_brief["memory_recovery"]["failed_at"] = datetime.now(UTC).isoformat()
    assert 0 < recovery.retry_after(w) <= 30


def test_execution_locks_are_keyed_and_reject_duplicate_sessions():
    from lifereel_api.core.database import SessionLocal
    from lifereel_api.modules.production.locking import execution_lock

    key = uuid4()
    with SessionLocal() as db, execution_lock(db, key) as first:
        assert first
        with execution_lock(db, key) as duplicate:
            assert not duplicate
        with execution_lock(db, uuid4()) as other:
            assert other
    with SessionLocal() as db, execution_lock(db, key) as released:
        assert released


def test_budget_blocks_next_memory_call(client):
    from lifereel_api.core.config import get_settings
    from lifereel_api.core.database import SessionLocal
    from lifereel_api.modules.billing.models import UsageEvent
    from lifereel_api.modules.billing.usage import _context
    from lifereel_api.modules.interview.models import InterviewTurnWorkflow

    person = client.post("/v1/persons", json={"display_name": "费用限制测试"}).json()
    session = client.post("/v1/interviews", json={"subject_id": person["id"]}).json()
    workflow = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "answer_text": "1952年出生。",
            "idempotency_key": "budget-limit-test",
        },
    ).json()
    tenant = get_settings().default_tenant_id
    with SessionLocal() as db:
        w = db.get(InterviewTurnWorkflow, UUID(workflow["id"]))
        state = w.script_brief["memory_recovery"]
        db.add(
            UsageEvent(
                tenant_id=tenant,
                operation="memory",
                reference=str(w.id),
                model="test",
                status="succeeded",
                duration_ms=1,
                usage={},
                metering={"retail_nano": recovery.MAX_RETAIL_NANO},
            )
        )
        db.commit()
        token = _context.set((tenant, "memory", str(w.id)))
        try:
            with pytest.raises(ApiError) as caught:
                recovery.check_call_budget()
            assert caught.value.code.value == "MEMORY_RETRY_LIMIT_REACHED"
            recovery.failure(db, w, caught.value)
            assert not recovery.allowed(w)
            assert w.script_brief["memory_recovery"]["runs"] == state["runs"]
        finally:
            _context.reset(token)


def test_completed_claim_and_graph_survive_biography_failure(client, monkeypatch):
    from lifereel_api.core.config import get_settings
    from lifereel_api.core.database import SessionLocal
    from lifereel_api.modules.billing.usage import _context
    from lifereel_api.modules.interview.models import InterviewTurnWorkflow
    from lifereel_api.modules.jobs import service as jobs
    from lifereel_api.modules.memory.models import MemoryClaim, MemoryEntity
    from lifereel_api.modules.memory.schemas import MemoryCompileRequest
    from lifereel_api.modules.memory.service import compile_memories

    person = client.post("/v1/persons", json={"display_name": "恢复测试"}).json()
    chapter = client.get("/v1/chapters").json()[0]
    session = client.post(
        "/v1/interviews", json={"subject_id": person["id"], "chapter_id": chapter["id"]}
    ).json()
    monkeypatch.setattr(jobs, "enqueue", lambda _: None)
    # Queue without running the AI workflow.
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://test/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "test")
    get_settings.cache_clear()
    counts = {"claim": 0, "graph": 0, "biography": 0}
    fix = False

    def response(self, system, user):
        if "证据整理员" in system:
            counts["claim"] += 1
            return {"claim_text": "和父亲生活", "claim_type": "relationship", "confidence": 0.9}
        if "知识图谱整理员" in system:
            counts["graph"] += 1
            claim_id = json.loads(user)["claims"][0]["claim_id"]
            return {
                "entities": [
                    {
                        "name": "父亲",
                        "normalized_name": "父亲",
                        "entity_type": "person",
                        "relationship": "父亲",
                        "source_claim_ids": [claim_id],
                    }
                ],
                "timeline": [],
                "conflicts": [],
            }
        counts["biography"] += 1
        return {"biography": "他和父亲生活。" if fix else "字" * 261}

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", response)
    try:
        w = client.post(
            f"/v1/interviews/{session['id']}/turns",
            json={
                "round_id": session["rounds"][0]["id"],
                "answer_text": "和父亲生活",
                "idempotency_key": "checkpoint-test-01",
                "asset_ids": [],
            },
        ).json()
        tenant = get_settings().default_tenant_id
        token = _context.set((tenant, "memory", w["id"]))
        try:
            with SessionLocal() as db:
                with pytest.raises(ApiError):
                    compile_memories(
                        db, tenant, MemoryCompileRequest(interview_session_id=UUID(session["id"]))
                    )
                db.rollback()
                assert len(list(db.scalars(select(MemoryClaim)))) == 1
                assert len(list(db.scalars(select(MemoryEntity)))) == 1
                assert db.get(InterviewTurnWorkflow, UUID(w["id"])).script_brief[
                    "memory_checkpoints"
                ]
                fix = True
                compile_memories(
                    db, tenant, MemoryCompileRequest(interview_session_id=UUID(session["id"]))
                )
                assert counts == {"claim": 1, "graph": 1, "biography": 3}
        finally:
            _context.reset(token)
    finally:
        get_settings.cache_clear()

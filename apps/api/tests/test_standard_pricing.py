from uuid import UUID, uuid4

import pytest
from test_billing import prepare_chapter
from test_live_interview_workflow import _start
from test_production_chapters import make_script

from lifereel_api.core.config import Settings, get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing import service as billing
from lifereel_api.modules.interview import service as interviews
from lifereel_api.modules.jobs import service as jobs
from lifereel_api.modules.memory import service as memories


@pytest.fixture(autouse=True)
def standard_pricing(legacy_pricing, monkeypatch):
    for field in (
        "billing_script_chapter_cents", "billing_video_cents_per_second", "billing_price_version",
    ):
        monkeypatch.setattr(get_settings(), field, Settings.model_fields[field].default)


def test_current_catalogue_preserves_welcome_credit(client):
    wallet = client.get("/v1/wallet").json()
    assert wallet["available_cents"] == 2000
    assert wallet["prices"]["script_chapter_cents"] == 40
    assert wallet["prices"]["video_cents_per_second"] == 80
    assert wallet["prices"]["version"] == "standard-2026-09-luna20"


def test_manual_updates_and_replay_use_current_catalogue(client):
    payload = {**prepare_chapter(client), "idempotency_key": str(uuid4())}
    for _ in range(2):
        assert client.post("/v1/scripts/generate", json=payload).status_code == 201
    assert client.get("/v1/wallet").json()["available_cents"] == 1960
    payload["idempotency_key"] = str(uuid4())
    assert client.post("/v1/scripts/generate", json=payload).status_code == 201
    assert client.get("/v1/wallet").json()["available_cents"] == 1920


def turn_payload(session):
    return {
        "round_id": session["rounds"][-1]["id"],
        "answer_text": "1968年，我和父母在泉州生活。",
        "idempotency_key": str(uuid4()),
    }


def test_interview_reserves_before_memory_and_charges_once(client, monkeypatch):
    _, _, session = _start(client)
    original = memories.compile_memories

    def check_reserved(db, tenant_id, payload):
        wallet = billing.lock_wallet(db, tenant_id)
        assert wallet.frozen_bonus_cents == 40
        db.commit()
        return original(db, tenant_id, payload)

    monkeypatch.setattr(memories, "compile_memories", check_reserved)
    payload = turn_payload(session)
    for _ in range(2):
        assert client.post(f"/v1/interviews/{session['id']}/turns", json=payload).status_code == 202
    wallet = client.get("/v1/wallet").json()
    assert wallet["available_cents"] == 1960
    assert wallet["frozen_cents"] == 0
    assert client.get("/v1/wallet/ledger?event=consume").json()["total"] == 1


def test_insufficient_funds_stops_before_any_interview_ai(client, monkeypatch):
    _, _, session = _start(client)
    with SessionLocal() as db:
        billing.reserve(db, get_settings().default_tenant_id, "other", 1900, "video", "test", {})
        db.commit()

    def unexpected(*args, **kwargs):
        pytest.fail("Memory AI must not run before sufficient credit is reserved")

    monkeypatch.setattr(memories, "compile_memories", unexpected)
    result = client.post(f"/v1/interviews/{session['id']}/turns", json=turn_payload(session))
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "WALLET_INSUFFICIENT_BALANCE"
    assert client.get("/v1/wallet").json()["available_cents"] == 100


def test_preprocessing_failure_releases_and_retry_keeps_original_price(client, monkeypatch):
    _, _, session = _start(client)
    original = memories.compile_memories

    def fail(*args, **kwargs):
        raise ApiError(502, ErrorCode.MEMORY_LLM_REQUEST_FAILED)

    monkeypatch.setattr(memories, "compile_memories", fail)
    result = client.post(f"/v1/interviews/{session['id']}/turns", json=turn_payload(session))
    assert result.status_code == 502
    wallet = client.get("/v1/wallet").json()
    assert wallet["available_cents"] == 2000
    assert wallet["frozen_cents"] == 0
    monkeypatch.setattr(memories, "compile_memories", original)
    monkeypatch.setattr(get_settings(), "billing_script_chapter_cents", 299)
    workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    workflow_id = workspace["latest_workflow"]["id"]
    assert client.post(f"/v1/internal/interview-turns/{workflow_id}/execute").status_code == 200
    assert client.get("/v1/wallet").json()["available_cents"] == 2000


def test_saved_script_remains_charged_when_followup_fails(client, monkeypatch):
    _, _, session = _start(client)
    original = interviews.suggest_next_question

    def fail(*args, **kwargs):
        raise ApiError(502, ErrorCode.INTERVIEW_LLM_REQUEST_FAILED)

    monkeypatch.setattr(interviews, "suggest_next_question", fail)
    assert client.post(
        f"/v1/interviews/{session['id']}/turns", json=turn_payload(session)
    ).status_code == 502
    assert client.get("/v1/wallet").json()["available_cents"] == 1960
    monkeypatch.setattr(interviews, "suggest_next_question", original)
    workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    workflow_id = workspace["latest_workflow"]["id"]
    assert client.post(f"/v1/internal/interview-turns/{workflow_id}/execute").status_code == 200
    assert client.get("/v1/wallet").json()["available_cents"] == 1801


def test_thirty_second_video_costs_24_not_covered_by_welcome_credit(client, monkeypatch):
    project, scenes = make_script(client)
    monkeypatch.setattr(get_settings(), "execute_mock_jobs_inline", False)
    monkeypatch.setattr(jobs, "enqueue", lambda _: None)
    payload = {
        "project_id": str(project.id), "scene_id": str(scenes[0].id), "quoted_amount_cents": 2400,
    }
    result = client.post("/v1/production/runs", json=payload)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "WALLET_INSUFFICIENT_BALANCE"
    # Add isolated test funding; do not change the welcome grant to make a video affordable.
    with SessionLocal() as db:
        billing.lock_wallet(db, UUID(str(get_settings().default_tenant_id))).paid_cents = 1000
        db.commit()
    old_quote = client.post("/v1/production/runs", json={**payload, "quoted_amount_cents": 600})
    assert old_quote.status_code == 409
    assert old_quote.json()["error"]["code"] == "BILLING_QUOTE_CHANGED"
    run = client.post("/v1/production/runs", json=payload)
    assert run.status_code == 201
    assert run.json()["output_manifest"]["billing_quote"]["amount_cents"] == 2400
    wallet = client.get("/v1/wallet").json()
    assert wallet["frozen_cents"] == 2400
    assert wallet["available_cents"] == 600

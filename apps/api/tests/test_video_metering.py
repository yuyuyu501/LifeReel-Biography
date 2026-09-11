from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from test_production_chapters import make_script

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.billing import service as billing
from lifereel_api.modules.billing import tokens, video
from lifereel_api.modules.billing.models import UsageEvent
from lifereel_api.modules.billing.usage import record, track_usage
from lifereel_api.modules.jobs import service as jobs
from lifereel_api.modules.production.models import ProductionRun
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


@pytest.fixture
def video_case(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "billing_video_mode", "tokens")
    monkeypatch.setattr(settings, "billing_text_mode", "tokens")
    monkeypatch.setattr(settings, "volcengine_api_key", "synthetic")
    monkeypatch.setattr(settings, "volcengine_video_model", video.MODEL)
    monkeypatch.setattr(settings, "volcengine_video_resolution", "720p")
    monkeypatch.setattr(jobs, "enqueue", lambda _: None)
    project, scenes = make_script(client)
    payload = {"project_id": str(project.id), "scene_id": str(scenes[0].id),
               "provider": "volcengine-seedance", "quoted_amount_cents": 2400}
    return client, payload, scenes


def start(case):
    client, payload, _ = case
    response = client.post("/v1/production/runs", json=payload)
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def receipt(run_id, task, usage, status="succeeded", model=video.MODEL):
    @track_usage("video")
    def save(db, tenant_id, run_id):
        record(model, status, usage, 1, task)

    with SessionLocal() as db:
        save(db, get_settings().default_tenant_id, run_id)


def finish(run_id, success=True):
    with SessionLocal() as db:
        run = db.get(ProductionRun, run_id)
        run.status = "completed" if success else "failed"
        billing.video_finish(db, run, success)
        db.commit()
        return run.output_manifest["billing"]


@pytest.mark.parametrize("balance", [1, 2000])
def test_positive_balance_allows_full_hold_but_not_a_second_spend(video_case, balance):
    client, payload, scenes = video_case
    with SessionLocal() as db:
        billing.lock_wallet(db, get_settings().default_tenant_id).bonus_cents = balance
        db.commit()
    run_id = start(video_case)
    wallet = client.get("/v1/wallet").json()
    assert wallet["available_cents"] == balance - 2400
    assert wallet["frozen_cents"] == 2400
    assert wallet["debt_cents"] == 0
    assert client.post("/v1/production/runs", json=payload).json()["id"] == str(run_id)
    second = client.post("/v1/production/runs", json={**payload, "scene_id": str(scenes[1].id)})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "WALLET_INSUFFICIENT_BALANCE"
    assert len(client.get("/v1/production/runs").json()) == 1


@pytest.mark.parametrize("balance", [0, -1, -500])
def test_nonpositive_balance_blocks_new_work(video_case, balance):
    client, payload, _ = video_case
    with SessionLocal() as db:
        wallet = billing.lock_wallet(db, get_settings().default_tenant_id)
        wallet.bonus_cents = 0
        wallet.paid_cents = balance
        db.commit()
    response = client.post("/v1/production/runs", json=payload)
    assert response.status_code == 409
    assert client.get("/v1/production/runs").json() == []


@pytest.mark.parametrize("count,cents,remainder", [
    (100000, 345, 0), (649800, 2241, 8100000), (1000000, 3450, 0),
])
def test_settlement_returns_difference_or_charges_debt_once(video_case, count, cents, remainder):
    client, _, _ = video_case
    run_id = start(video_case)
    receipt(run_id, "paid-task", {"completion_tokens": count})
    result = finish(run_id)
    assert result["charged_cents"] == cents
    assert result["returned_cents"] == max(0, 2400 - cents)
    assert result["additional_cents"] == max(0, cents - 2400)
    assert finish(run_id) == result
    wallet = client.get("/v1/wallet").json()
    assert wallet["available_cents"] == 2000 - cents
    assert wallet["frozen_cents"] == 0
    assert wallet["token_remainder_nano"] == remainder
    assert wallet["debt_cents"] == max(0, cents - 2000)
    assert client.get("/v1/wallet/ledger?event=consume").json()["total"] == 1


def test_failed_task_retains_successful_segment_cost_and_retry_bills_only_new_usage(video_case):
    client, _, _ = video_case
    run_id = start(video_case)
    receipt(run_id, "first", {"completion_tokens": 100000})
    receipt(run_id, "failed", {}, "failed")
    assert finish(run_id, False)["charged_cents"] == 345
    with SessionLocal() as db:
        run = db.get(ProductionRun, run_id)
        billing.video_reserve(db, run)
        db.commit()
    receipt(run_id, "first", {"completion_tokens": 100000})
    receipt(run_id, "replacement", {"completion_tokens": 100000})
    assert finish(run_id)["charged_cents"] == 690
    assert client.get("/v1/wallet").json()["available_cents"] == 1310


def test_failure_before_any_provider_consumption_releases_budget(video_case):
    client, _, _ = video_case
    run_id = start(video_case)
    assert finish(run_id, False)["charged_cents"] == 0
    assert client.get("/v1/wallet").json()["available_cents"] == 2000


@pytest.mark.parametrize("usage", [{}, {"total_tokens": 100}, {"completion_tokens": True}])
def test_missing_or_invalid_receipt_retains_hold(video_case, usage):
    client, _, _ = video_case
    run_id = start(video_case)
    receipt(run_id, "unknown-usage", usage)
    assert finish(run_id)["status"] == "pending"
    assert client.get("/v1/wallet").json()["frozen_cents"] == 2400
    assert client.get("/v1/wallet/ledger?event=consume").json()["total"] == 0


def test_inflight_cloud_task_is_not_refunded_on_timeout(video_case):
    client, _, _ = video_case
    run_id = start(video_case)
    receipt(run_id, "inflight", {"requested_duration_seconds": 15}, "submitted")
    assert finish(run_id, False)["status"] == "pending"
    assert client.get("/v1/wallet").json()["frozen_cents"] == 2400
    receipt(run_id, "inflight", {"completion_tokens": 100000})
    assert finish(run_id)["charged_cents"] == 345
    assert client.get("/v1/wallet").json()["frozen_cents"] == 0


def test_video_planner_uses_existing_hold_and_is_included_in_final_usage(video_case, monkeypatch):
    client, _, _ = video_case
    run_id = start(video_case)

    def response(*args, **kwargs):
        assert kwargs["json"]["max_tokens"] == tokens.MAX_OUTPUT
        return httpx.Response(200, request=httpx.Request("POST", "https://synthetic.test"), json={
            "id": "planner", "usage": {"prompt_tokens": 10000, "completion_tokens": 1000},
            "choices": [{"message": {"content": "{}"}}],
        })

    monkeypatch.setattr(httpx, "post", response)

    @track_usage("video")
    def planner(db, tenant_id, run_id):
        return OpenAICompatibleClient(
            "https://ark.cn-beijing.volces.com/api/v3", "synthetic", tokens.MODEL,
        ).chat_json("test", "test")

    with SessionLocal() as db:
        assert planner(db, get_settings().default_tenant_id, run_id) == {}
    assert client.get("/v1/wallet").json()["frozen_cents"] == 2400
    receipt(run_id, "clip", {"completion_tokens": 100000})
    assert finish(run_id)["charged_cents"] == 346
    wallet = client.get("/v1/wallet").json()
    assert wallet["token_remainder_nano"] == 5000000
    with SessionLocal() as db:
        events = db.scalars(select(UsageEvent).where(UsageEvent.reference == str(run_id)))
        assert all(e.metering["status"] == "settled" for e in events)


def test_crediting_money_reduces_debt_before_restoring_spending(video_case):
    client, _, _ = video_case
    run_id = start(video_case)
    receipt(run_id, "large", {"completion_tokens": 1000000})
    finish(run_id)
    with SessionLocal() as db:
        wallet = billing.lock_wallet(db, get_settings().default_tenant_id)
        wallet.paid_cents += 500
        db.commit()
    assert client.get("/v1/wallet").json()["debt_cents"] == 950


def test_unpriced_model_fails_before_reserving(video_case, monkeypatch):
    client, payload, _ = video_case
    monkeypatch.setattr(get_settings(), "volcengine_video_model", "doubao-seedance-2-other")
    result = client.post("/v1/production/runs", json=payload)
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "BILLING_MODEL_UNPRICED"
    assert client.get("/v1/wallet").json()["frozen_cents"] == 0


def test_only_a_single_bounded_chapter_can_use_one_fixed_budget(video_case):
    client, payload, _ = video_case
    result = client.post("/v1/production/runs", json={**payload, "scene_id": None})
    assert result.status_code == 422
    assert client.get("/v1/wallet").json()["frozen_cents"] == 0


def test_later_complete_receipt_can_recover_missing_provider_usage(video_case):
    client, _, _ = video_case
    run_id = start(video_case)
    receipt(run_id, "late", {})
    assert finish(run_id)["status"] == "pending"
    receipt(run_id, "late", {"completion_tokens": 100000})
    assert finish(run_id)["charged_cents"] == 345
    assert client.get("/v1/wallet/usage").json()["total"] == 1


def test_operator_reconciliation_checks_receipt_identity_and_cannot_rebill(video_case):
    from lifereel_api.modules.billing.video_admin import reconcile

    run_id = start(video_case)
    receipt(run_id, "incomplete", {})
    finish(run_id)
    with SessionLocal() as db:
        event = db.scalar(select(UsageEvent).where(UsageEvent.reference == str(run_id)))
        with pytest.raises(ValueError):
            reconcile(db, run_id, event.id,
                      {"id": "wrong", "usage": {"completion_tokens": 100000}}, "test", "invoice")
        db.rollback()
        result = reconcile(db, run_id, event.id,
                           {"id": "incomplete", "usage": {"completion_tokens": 100000}},
                           "test", "invoice")
        assert result["charged_cents"] == 345
        with pytest.raises(ValueError):
            reconcile(db, run_id, event.id,
                      {"id": "incomplete", "usage": {"completion_tokens": 100000}},
                      "test", "invoice")


def test_segmented_pipeline_settles_native_receipts_only_after_assembly(client, monkeypatch):
    from test_segmented_production import setup_pipeline

    from lifereel_api.modules.production import segmented
    from lifereel_api.modules.production.providers import ProviderOutput

    payload = setup_pipeline(client, monkeypatch)
    monkeypatch.setattr(get_settings(), "billing_video_mode", "tokens")
    monkeypatch.setattr(get_settings(), "volcengine_video_resolution", "720p")
    tasks = []

    class Provider:
        def __init__(self, options):
            self.client = self

        def close(self):
            pass

        def submit_segment(self, prompt, duration, frame):
            task = f"segment-{len(tasks)}"
            tasks.append(task)
            record(video.MODEL, "submitted", {"requested_duration_seconds": duration}, 0, task)
            return task

        def fetch_segment(self, task, duration):
            record(video.MODEL, "succeeded", {"completion_tokens": 324900}, 0, task)
            return ProviderOutput(b"clip", "video/mp4", "mp4", {})

    monkeypatch.setattr(segmented, "VolcengineSeedanceProvider", Provider)
    created = client.post("/v1/production/runs", json=payload)
    assert created.status_code == 201
    run = created.json()
    url = f"/v1/production/runs/{run['id']}/execute"
    for _ in range(2):
        assert client.post(url).json()["status"] == "running"
        assert client.get("/v1/wallet").json()["frozen_cents"] == 2400
    final = client.post(url).json()
    assert final["status"] == "completed"
    assert final["output_manifest"]["billing"]["charged_cents"] == 2241
    assert client.post(url).json()["status"] == "completed"
    assert len(tasks) == 2
    assert client.get("/v1/wallet").json()["debt_cents"] == 241

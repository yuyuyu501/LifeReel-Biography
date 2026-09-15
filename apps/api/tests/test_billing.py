from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from test_production_chapters import make_script

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing import service as billing
from lifereel_api.modules.billing.models import LedgerEntry
from lifereel_api.modules.billing.usage import record, track_usage
from lifereel_api.modules.identity.models import Tenant
from lifereel_api.modules.jobs import service as jobs
from lifereel_api.modules.production import service as production
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.modules.production.providers import ProviderOutput, VideoProviderError
from lifereel_api.modules.script import service as scripts
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


def test_welcome_bonus_once_no_fake_recharge(client):
    for _ in range(3):
        wallet = client.get("/v1/wallet").json()
        assert wallet["available_cents"] == 2000
        assert wallet["paid_cents"] == 0
    ledger = client.get("/v1/wallet/ledger").json()
    assert ledger["total"] == 1
    assert ledger["items"][0]["event"] == "bonus"
    assert (
        client.post("/v1/wallet/recharge", json={"amount_cents": 100000, "paid": True}).status_code
        == 422
    )
    assert client.get("/v1/wallet").json()["available_cents"] == 2000


def test_charge_lifecycle_insufficient_funds_and_idempotency(client):
    tenant = get_settings().default_tenant_id
    with SessionLocal() as db:
        charge = billing.reserve(db, tenant, "test", 600, "video", "chapter", billing.prices())
        db.commit()
        assert charge.bonus_cents == 600
        assert billing.reserve(db, tenant, "test", 600, "video", "chapter", {}).id == charge.id
        db.commit()
        assert billing.available(billing.lock_wallet(db, tenant)) == 1400
        billing.transition(db, tenant, "test", False)
        billing.transition(db, tenant, "test", False)
        db.commit()
        assert billing.available(billing.lock_wallet(db, tenant)) == 2000
        retry = billing.reserve(db, tenant, "test", 999, "video", "chapter", {})
        assert retry.amount_cents == 600
        billing.transition(db, tenant, "test", True)
        billing.transition(db, tenant, "test", True)
        billing.transition(db, tenant, "test", False)
        db.commit()
        assert billing.available(billing.lock_wallet(db, tenant)) == 1400
        with pytest.raises(ApiError) as exc:
            billing.reserve(db, tenant, "large", 1500, "video", "large", {})
        assert exc.value.code == ErrorCode.WALLET_INSUFFICIENT_BALANCE
        db.rollback()
        assert (
            db.scalar(
                select(func.count()).select_from(LedgerEntry).where(LedgerEntry.event == "consume")
            )
            == 1
        )


def test_video_reserves_releases_retries_and_settles_once(client, monkeypatch):
    project, scenes = make_script(client)
    monkeypatch.setattr(get_settings(), "execute_mock_jobs_inline", False)
    monkeypatch.setattr(jobs, "enqueue", lambda _: None)
    failed = True

    class Provider:
        def render(self, *_):
            if failed:
                raise VideoProviderError("VIDEO_PROVIDER_FAILED")
            return ProviderOutput(b"{}", "application/json", "json", {})

    monkeypatch.setattr(production, "get_video_provider", lambda _: Provider())
    payload = {
        "project_id": str(project.id),
        "scene_id": str(scenes[0].id),
        "quoted_amount_cents": 600,
    }
    run = client.post("/v1/production/runs", json=payload).json()
    assert client.get("/v1/wallet").json()["frozen_cents"] == 600
    assert client.post("/v1/production/runs", json=payload).json()["id"] == run["id"]
    url = f"/v1/production/runs/{run['id']}/execute"
    assert client.post(url).json()["status"] == "failed"
    assert client.get("/v1/wallet").json()["available_cents"] == 2000
    monkeypatch.setattr(get_settings(), "billing_video_cents_per_second", 40)
    assert client.post(f"/v1/jobs/{run['job_id']}/retry").status_code == 200
    failed = False
    assert client.post(url).json()["status"] == "completed"
    assert client.post(url).json()["status"] == "completed"
    assert client.get("/v1/wallet").json()["available_cents"] == 1400
    assert client.get("/v1/wallet/ledger?event=consume").json()["total"] == 1
    result = client.post("/v1/production/runs", json={**payload, "scene_id": str(scenes[1].id)})
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "BILLING_QUOTE_CHANGED"


def prepare_chapter(client, subject_id=None, chapter_index=0):
    person = (
        {"id": subject_id}
        if subject_id
        else client.post("/v1/persons", json={"display_name": "Wallet test"}).json()
    )
    chapter = client.get("/v1/chapters").json()[chapter_index]
    interview = client.post(
        "/v1/interviews", json={"subject_id": person["id"], "chapter_id": chapter["id"]}
    ).json()
    client.post(
        f"/v1/interviews/{interview['id']}/rounds/{interview['rounds'][0]['id']}/answer",
        json={"answer_text": "我出生在杭州，小时候和姐姐一起上学。"},
    )
    assert (
        client.post(
            "/v1/memories/compile", json={"interview_session_id": interview["id"]}
        ).status_code
        == 200
    )
    return {"subject_id": person["id"], "chapter_id": chapter["id"], "mode": "single_chapter"}


def test_script_each_update_charges_and_failure_releases(client, monkeypatch):
    payload = prepare_chapter(client)
    original = scripts._generate_draft

    def fail(*args, **kwargs):
        raise ApiError(502, ErrorCode.SCRIPT_LLM_REQUEST_FAILED)

    monkeypatch.setattr(scripts, "_generate_draft", fail)
    assert client.post("/v1/scripts/generate", json=payload).status_code == 502
    assert client.get("/v1/wallet").json()["available_cents"] == 2000
    monkeypatch.setattr(scripts, "_generate_draft", original)
    for _ in range(3):
        assert client.post("/v1/scripts/generate", json=payload).status_code == 201
    assert client.get("/v1/wallet").json()["available_cents"] == 1994
    assert client.get("/v1/wallet/ledger?event=consume").json()["total"] == 3


def test_script_update_retry_is_idempotent_and_keeps_original_price(client, monkeypatch):
    payload = {**prepare_chapter(client), "idempotency_key": str(uuid4())}
    original = scripts._generate_draft

    def fail(*args, **kwargs):
        raise ApiError(502, ErrorCode.SCRIPT_LLM_REQUEST_FAILED)

    monkeypatch.setattr(scripts, "_generate_draft", fail)
    assert client.post("/v1/scripts/generate", json=payload).status_code == 502
    assert client.get("/v1/wallet").json()["available_cents"] == 2000
    monkeypatch.setattr(get_settings(), "billing_script_chapter_cents", 5)
    monkeypatch.setattr(scripts, "_generate_draft", original)
    first = client.post("/v1/scripts/generate", json=payload).json()
    assert client.get("/v1/wallet").json()["available_cents"] == 1998
    monkeypatch.setattr(scripts, "_generate_draft", fail)
    replay = client.post("/v1/scripts/generate", json=payload)
    assert replay.status_code == 201
    assert replay.json()["version_number"] == first["version_number"]
    assert client.get("/v1/wallet").json()["available_cents"] == 1998
    assert (
        client.post("/v1/scripts/generate", json={**payload, "title": "changed"}).status_code == 409
    )
    monkeypatch.setattr(scripts, "_generate_draft", original)
    assert (
        client.post(
            "/v1/scripts/generate", json={**payload, "idempotency_key": str(uuid4())}
        ).status_code
        == 201
    )
    assert client.get("/v1/wallet").json()["available_cents"] == 1993


def test_script_insufficient_balance_stops_before_generation(client, monkeypatch):
    payload = prepare_chapter(client)
    with SessionLocal() as db:
        billing.reserve(db, get_settings().default_tenant_id, "other", 1999, "video", "test", {})
        db.commit()

    def unexpected(*args, **kwargs):
        raise AssertionError("AI must not run without enough available balance")

    monkeypatch.setattr(scripts, "_generate_draft", unexpected)
    result = client.post("/v1/scripts/generate", json=payload)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "WALLET_INSUFFICIENT_BALANCE"
    assert client.get("/v1/wallet").json()["available_cents"] == 1


def test_multi_chapter_update_charges_each_chapter_each_time(client):
    first = prepare_chapter(client)
    prepare_chapter(client, first["subject_id"], 1)
    payload = {"subject_id": first["subject_id"], "mode": "multi_chapter"}
    for _ in range(2):
        result = client.post("/v1/scripts/generate", json=payload)
        assert result.status_code == 201
        assert len(result.json()["scenes"]) == 2
    assert client.get("/v1/wallet").json()["available_cents"] == 1992
    assert client.get("/v1/wallet/ledger?event=consume").json()["total"] == 4


def test_registration_disabled_by_default_and_bonus_in_same_transaction(client, monkeypatch):
    from datetime import timedelta
    from uuid import uuid4

    from lifereel_api.core.models import utcnow
    from lifereel_api.modules.auth import sms
    from lifereel_api.modules.auth.models import SmsChallenge

    monkeypatch.setattr(get_settings(), "auth_token_secret", "billing-registration-secret")
    challenge_id = uuid4()
    with SessionLocal() as db:
        db.add(
            SmsChallenge(
                id=challenge_id,
                phone="13800138000",
                purpose="register",
                code_hash=sms.digest(challenge_id, "13800138000", "register", "123456"),
                expires_at=utcnow() + timedelta(minutes=5),
            )
        )
        db.commit()
    payload = {
        "phone": "13800138000",
        "challenge_id": str(challenge_id),
        "code": "123456",
        "password": "TestPass123!",
        "display_name": "New family",
    }
    assert client.post("/v1/auth/register", json=payload).status_code == 403
    monkeypatch.setattr(get_settings(), "registration_enabled", True)
    result = client.post("/v1/auth/register", json=payload)
    assert result.status_code == 201
    assert client.post("/v1/auth/register", json=payload).status_code == 400
    tenant = UUID(result.json()["tenant_id"])
    with SessionLocal() as db:
        assert billing.available(billing.lock_wallet(db, tenant)) == 2000
        assert (
            db.scalar(
                select(func.count()).select_from(LedgerEntry).where(LedgerEntry.tenant_id == tenant)
            )
            == 1
        )


def test_wallet_ledger_and_usage_are_tenant_isolated(client):
    client.get("/v1/wallet")
    other = uuid4()
    with SessionLocal() as db:
        db.add(Tenant(id=other, name="Other family", slug=str(other)))
        db.commit()
        billing.reserve(db, other, "other", 100, "video", "private-title", {})
        db.commit()
    assert "private-title" not in client.get("/v1/wallet/ledger").text
    assert client.get("/v1/wallet").json()["frozen_cents"] == 0
    assert client.get("/v1/wallet/ledger?page=0").status_code == 422
    assert client.get("/v1/wallet/ledger?page=2").json()["items"] == []


def test_usage_persists_actual_tokens_without_prompts_or_credentials(client, monkeypatch):
    def post(*args, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://model.test"),
            json={
                "id": "call-123",
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 7, "total_tokens": 49},
            },
        )

    monkeypatch.setattr(httpx, "post", post)

    @track_usage("script")
    def generate(db, tenant_id):
        return OpenAICompatibleClient("https://model.test", "private-key", "test-model").chat(
            "private-prompt", "private-input"
        )

    with SessionLocal() as db:
        assert generate(db, get_settings().default_tenant_id) == "answer"
    response = client.get("/v1/wallet/usage")
    assert response.json()["items"][0]["usage"]["total_tokens"] == 49
    assert "private-key" not in response.text and "private-prompt" not in response.text


def test_usage_deduplicates_task_receipts_but_keeps_failure_and_submission(client):
    @track_usage("video")
    def receipts(db, tenant_id):
        for _ in range(2):
            record("test-video", "submitted", {"requested_duration_seconds": 15}, 0, "task-1")
            record("test-video", "failed", {}, 0, "task-1", "VIDEO_PROVIDER_FAILED")
            record("test-video", "succeeded", {"total_tokens": 100}, 0, "task-2")

    with SessionLocal() as db:
        receipts(db, get_settings().default_tenant_id)
    response = client.get("/v1/wallet/usage").json()
    assert response["total"] == 3
    assert {row["status"] for row in response["items"]} == {"submitted", "failed", "succeeded"}


def test_video_save_failure_rolls_back_asset_and_releases_credit(client, monkeypatch):
    project, scenes = make_script(client)
    monkeypatch.setattr(get_settings(), "execute_mock_jobs_inline", False)
    monkeypatch.setattr(jobs, "enqueue", lambda _: None)

    class Provider:
        def render(self, *_):
            return ProviderOutput(b"{}", "application/json", "json", {})

    def audit_failure(*args, **kwargs):
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(production, "get_video_provider", lambda _: Provider())
    monkeypatch.setattr(production.governance, "audit", audit_failure)
    run = client.post(
        "/v1/production/runs",
        json={
            "project_id": str(project.id),
            "scene_id": str(scenes[0].id),
        },
    ).json()
    with SessionLocal() as db, execution_lock(db, UUID(run["id"])) as acquired:
        assert acquired
        assert client.post(f"/v1/jobs/{run['job_id']}/retry").status_code == 409
        jobs.fail_job(
            db, get_settings().default_tenant_id, UUID(run["job_id"]), "WORKER_ERROR", None
        )
    assert client.get("/v1/wallet").json()["frozen_cents"] == 600
    failed = client.post(f"/v1/production/runs/{run['id']}/execute").json()
    assert failed["status"] == "failed"
    assert failed["assets"] == []
    assert client.get("/v1/wallet").json()["available_cents"] == 2000
    assert client.get("/v1/wallet/ledger?event=consume").json()["total"] == 0

    def queue_failure(_):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(jobs, "enqueue", queue_failure)
    assert client.post(f"/v1/jobs/{run['job_id']}/retry").status_code == 503
    assert client.get("/v1/wallet").json()["frozen_cents"] == 0

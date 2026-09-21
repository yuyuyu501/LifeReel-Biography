import hashlib
import hmac
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Lock
from uuid import UUID, uuid4

import pytest

from lifereel_api.core.capacity import resource
from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.jobs import dispatch
from lifereel_api.modules.jobs.models import Job


@pytest.fixture
def worker_headers(monkeypatch):
    monkeypatch.setattr(get_settings(), "api_access_key", "test-worker-secret")
    return {
        "X-Worker-Key": hmac.new(
            b"test-worker-secret",
            b"lifereel-worker-v1",
            hashlib.sha256,
        ).hexdigest()
    }


def add_jobs(kind, count):
    with SessionLocal() as db:
        for _ in range(count):
            db.add(Job(tenant_id=get_settings().default_tenant_id, kind=kind, payload={}))
        db.commit()


def test_worker_routes_require_separate_credential(client, worker_headers):
    for headers in ({}, {"X-API-Key": "test-worker-secret"}, {"X-Worker-Key": "invalid"}):
        assert (
            client.post(
                "/v1/internal/worker/claim", json={"lane": "interview"}, headers=headers
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/v1/internal/worker/claim", json={"lane": "interview"}, headers=worker_headers
        ).json()
        is None
    )


def test_admission_limits_and_independent_video_lane(client, worker_headers):
    add_jobs("interview.turn.process", 10)
    add_jobs("production.render", 5)

    def claim(lane):
        return client.post(
            "/v1/internal/worker/claim", json={"lane": lane}, headers=worker_headers
        ).json()

    text_claims = [claim("interview") for _ in range(5)]
    assert len({c["job_id"] for c in text_claims if c}) == 3
    assert text_claims[3:] == [None, None]
    assert claim("video") is not None
    assert claim("video") is None


def test_expired_lease_reclaimed_and_old_owner_cannot_release(client, worker_headers):
    add_jobs("interview.turn.process", 1)
    with SessionLocal() as db:
        old = dispatch.claim_job(db, "interview")
        job = db.get(Job, UUID(old["job_id"]))
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        new = dispatch.claim_job(db, "interview")
        assert old["job_id"] == new["job_id"] and old["token"] != new["token"]
    base = f"/v1/internal/worker/{old['job_id']}"
    for action in ("heartbeat", "release"):
        assert client.post(
            f"{base}/{action}", json={"token": old["token"]}, headers=worker_headers
        ).json() == {"owned": False}
    assert (
        client.post(
            f"{base}/execute", json={"token": old["token"]}, headers=worker_headers
        ).status_code
        == 409
    )
    assert client.post(
        f"{base}/heartbeat", json={"token": new["token"]}, headers=worker_headers
    ).json() == {"owned": True}


def queued_turn(client, monkeypatch):
    from test_live_interview_workflow import _start

    _, _, session = _start(client)
    monkeypatch.setattr(get_settings(), "execute_mock_jobs_inline", False)
    workflow = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "round_id": session["rounds"][-1]["id"],
            "answer_text": "1952年我在泉州出生。",
            "idempotency_key": str(uuid4()),
        },
    ).json()
    with SessionLocal() as db:
        claim = dispatch.claim_job(db, "interview")
    return workflow, claim


def test_database_delivery_and_completed_replay_do_not_repeat_work(client, monkeypatch):
    from lifereel_api.modules.orchestration import service

    workflow, claim = queued_turn(client, monkeypatch)
    with SessionLocal() as db:
        assert dispatch.execute_claim(db, UUID(claim["job_id"]), UUID(claim["token"])) == {
            "status": "completed",
        }
        monkeypatch.setattr(service, "execute_turn", lambda *a, **kw: pytest.fail("duplicate AI"))
        assert dispatch.execute_claim(db, UUID(claim["job_id"]), UUID(claim["token"])) == {
            "status": "completed",
        }
        assert db.get(Job, UUID(claim["job_id"])).attempt_count == 1


def test_expired_lease_cannot_repeat_work_while_first_delivery_holds_lock(client, monkeypatch):
    from lifereel_api.modules.orchestration import service
    from lifereel_api.modules.production.locking import execution_lock

    _, first = queued_turn(client, monkeypatch)
    job_id = UUID(first["job_id"])
    with SessionLocal() as original, execution_lock(original, job_id) as acquired:
        assert acquired
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
            second = dispatch.claim_job(db, "interview")
            assert second["token"] != first["token"]
            monkeypatch.setattr(
                service, "execute_turn", lambda *a, **k: pytest.fail("duplicate AI"),
            )
            assert dispatch.execute_claim(db, job_id, UUID(second["token"])) == {
                "status": "running",
            }
            assert job.attempt_count == 0


def test_interrupted_paid_turn_does_not_resubmit_without_receipt(client, monkeypatch):
    from lifereel_api.modules.billing import service as billing
    from lifereel_api.modules.interview.models import InterviewTurnWorkflow

    workflow, claim = queued_turn(client, monkeypatch)
    with SessionLocal() as db:
        job = db.get(Job, UUID(claim["job_id"]))
        w = db.get(InterviewTurnWorkflow, UUID(workflow["id"]))
        job.status = w.status = "running"
        billing.reserve(
            db,
            job.tenant_id,
            "uncertain-call",
            40,
            "token_hold",
            "test",
            {
                "reference": workflow["id"],
            },
        )
        db.commit()
        assert dispatch.execute_claim(db, job.id, UUID(claim["token"]))["status"] == "failed"
        assert w.error_code == "BILLING_USAGE_PENDING"
        assert client.get("/v1/wallet").json()["frozen_cents"] == 40


@pytest.mark.parametrize("name,maximum", [("asr", 1), ("assembly", 1), ("llm", 4)])
def test_resource_limits_under_ten_concurrent_requests(monkeypatch, name, maximum):
    monkeypatch.setattr(get_settings(), "llm_min_interval_seconds", 0)
    lock = Lock()
    active = peak = 0

    def work(_):
        nonlocal active, peak
        with resource(name):
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(work, range(10)))
    assert peak == maximum

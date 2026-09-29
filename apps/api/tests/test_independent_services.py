"""Regression checks for process ownership, publication, replay and billing boundaries."""

import json
import re
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from lifereel_api.architecture.internal import Envelope, signature
from lifereel_api.architecture.runtime import create_app
from lifereel_api.architecture.topology import ROUTERS
from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing import service as billing
from lifereel_api.modules.billing.commands import enqueue_transition
from lifereel_api.modules.billing.internal import command
from lifereel_api.modules.billing.models import LedgerEntry
from lifereel_api.modules.identity.models import Tenant
from lifereel_api.modules.jobs.dispatch import claim_job, execute_claim
from lifereel_api.modules.jobs.events import JobDelivery, OutboxEvent
from lifereel_api.modules.jobs.outbox import dispatch_batch
from lifereel_api.modules.jobs.service import create_job
from lifereel_api.providers.invocations import invoke
from lifereel_api.providers.models import ModelInvocation


def tenant(db):
    row = Tenant(name="Isolated service test", slug=str(uuid4()))
    db.add(row)
    db.commit()
    return row.id


def test_owned_routes_and_independent_entrypoints():
    root = Path(__file__).resolve().parents[3]
    expected = {
        "identity": "/v1/persons",
        "interview": "/v1/interviews",
        "memory": "/v1/memories",
        "script": "/v1/scripts",
        "media": "/v1/production/runs",
        "billing": "/v1/wallet",
        "tasks": "/v1/jobs",
        "model-gateway": "/v1/providers",
    }
    for name in ROUTERS:
        assert (root / "services" / name / "Dockerfile").is_file()
        paths = set(create_app(name).openapi()["paths"])
        assert expected[name] in paths
        for other, path in expected.items():
            if other != name:
                assert path not in paths, (name, path)


def test_gateway_routes_every_public_api_to_its_owner():
    root = Path(__file__).resolve().parents[3]
    nginx = (root / "services/gateway/nginx.conf").read_text(encoding="utf-8")
    routes = [
        (re.compile(pattern), owner)
        for pattern, owner in re.findall(r"^\s*~(\S+)\s+([a-z-]+):8000;", nginx, re.MULTILINE)
    ]
    for owner in ROUTERS:
        for path in create_app(owner).openapi()["paths"]:
            if path.startswith("/v1/") and not path.startswith("/v1/internal/"):
                assert [target for pattern, target in routes if pattern.match(path)] == [owner], (
                    path
                )


def test_every_service_preserves_configured_cors_policy(monkeypatch):
    monkeypatch.setattr(get_settings(), "api_cors_origins", ["https://qa.invalid"])
    for owner in ROUTERS:
        client = TestClient(create_app(owner))
        response = client.options(
            "/health",
            headers={"Origin": "https://qa.invalid", "Access-Control-Request-Method": "GET"},
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://qa.invalid"
        assert response.headers["access-control-allow-credentials"] == "true"
        assert (
            client.options(
                "/health",
                headers={
                    "Origin": "https://untrusted.invalid",
                    "Access-Control-Request-Method": "GET",
                },
            ).status_code
            == 400
        )


@pytest.mark.parametrize(
    "source,operation,payload",
    [
        ("interview", "llm.chat", {}),
        (
            "worker-media",
            "model.video-request",
            {
                "method": "POST",
                "path": "/contents/generations/tasks",
                "arguments": {"headers": {"Authorization": "override"}},
            },
        ),
    ],
)
def test_invalid_internal_model_payload_rejected_before_execution(
    monkeypatch, source, operation, payload
):
    monkeypatch.setattr(get_settings(), "api_access_key", "isolated-signature-key")
    body = json.dumps({"tenant_id": str(uuid4()), "payload": payload}).encode()
    path = f"/internal/v1/{operation}"
    stamp = str(int(time.time()))
    headers = {
        "X-Service-Name": source,
        "X-Service-Time": stamp,
        "X-Service-Signature": signature(source, stamp, path, body),
    }
    with TestClient(create_app("model-gateway")) as client:
        assert client.post(path, content=body, headers=headers).status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ModelInvocation)) == 0


def test_internal_authentication_and_operation_allowlist(monkeypatch):
    monkeypatch.setattr(get_settings(), "api_access_key", "isolated-signature-key")
    with SessionLocal() as db:
        tenant_id = tenant(db)
    body = (
        Envelope(tenant_id=tenant_id, payload={"interview_session_id": str(uuid4())})
        .model_dump_json()
        .encode()
    )
    path = "/internal/v1/memory.compile"
    stamp = str(int(time.time()))
    headers = {
        "X-Service-Name": "worker-interview",
        "X-Service-Time": stamp,
        "X-Service-Signature": signature("worker-interview", stamp, path, body),
        "Content-Type": "application/json",
    }
    with TestClient(create_app("memory")) as client:
        assert client.post(path, content=body).status_code == 401
        assert client.post(path, content=body + b" ", headers=headers).status_code == 401
        assert client.post(path, content=body, headers=headers).status_code == 404
        headers["X-Service-Name"] = "billing"
        headers["X-Service-Signature"] = signature("billing", stamp, path, body)
        assert client.post(path, content=body, headers=headers).status_code == 403


def test_outbox_publication_gates_claims_and_deduplicates(monkeypatch):
    monkeypatch.setenv("SERVICE_MODE", "distributed")
    monkeypatch.setenv("LIFEREEL_SERVICE", "worker-interview")
    monkeypatch.setattr(get_settings(), "job_queue_backend", "database")
    with SessionLocal() as db:
        tenant_id = tenant(db)
        job, _ = create_job(db, tenant_id, "interview.turn.process", {}, "publication-test")
        db.commit()
        job_id = job.id
        assert claim_job(db, "interview") is None
    assert dispatch_batch() == 1
    with SessionLocal() as db:
        event = db.scalar(select(OutboxEvent))
        event.status = "pending"
        db.commit()
    assert dispatch_batch() == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(JobDelivery)) == 1
        claimed = claim_job(db, "interview")
        assert claimed["job_id"] == str(job_id)
        assert claim_job(db, "interview") is None
        monkeypatch.setenv("LIFEREEL_SERVICE", "tasks")
        from uuid import UUID

        with pytest.raises(ApiError) as error:
            execute_claim(db, job_id, UUID(claimed["token"]))
        assert error.value.status_code == 403


def test_billing_command_replay_debits_once(monkeypatch):
    with SessionLocal() as db:
        tenant_id = tenant(db)
        billing.reserve(db, tenant_id, "completed-script", 50, "script", "Test", {})
        db.commit()
        enqueue_transition(db, tenant_id, "completed-script", True)
        db.commit()
        event = db.scalar(select(OutboxEvent))
        data = {"event_id": str(event.id), **event.payload}
    monkeypatch.setenv("SERVICE_MODE", "distributed")
    monkeypatch.setenv("LIFEREEL_SERVICE", "billing")
    for _ in range(2):
        with SessionLocal() as db:
            assert command(db, tenant_id, data) == {"accepted": True}
            db.commit()
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(LedgerEntry).where(LedgerEntry.event == "consume")
            )
            == 1
        )
        wallet = billing.read_wallet(db, tenant_id)
        assert wallet.bonus_cents == get_settings().billing_welcome_bonus_cents - 50
        assert wallet.frozen_bonus_cents == 0


def test_completed_model_response_is_replayed_without_provider_call():
    calls = []
    with SessionLocal() as db:
        tenant_id = tenant(db)
        request = Envelope(
            tenant_id=tenant_id,
            usage_operation="memory",
            usage_reference=str(uuid4()),
            payload={"messages": [{"content": "synthetic"}]},
        )

        def provider(*args):
            calls.append(1)
            return {"output": {"claim": "derived fact"}}

        first = invoke(db, "memory", "llm.chat", request, provider)
        second = invoke(db, "memory", "llm.chat", request, provider)
        assert first == second and calls == [1]
        row = db.scalar(select(ModelInvocation))
        assert row.state == "completed"
        assert len(row.request_digest) == 64
        assert "synthetic" not in str(row.response)


@pytest.mark.parametrize("error_kind", ["transport", "service"])
def test_uncertain_model_request_is_never_reissued(error_kind):
    calls = []
    with SessionLocal() as db:
        tenant_id = tenant(db)
        request = Envelope(tenant_id=tenant_id, payload={"prompt": "synthetic"})

        def provider(*args):
            calls.append(1)
            if error_kind == "service":
                raise ApiError(503, ErrorCode.SERVICE_UNAVAILABLE)
            raise httpx.ReadError("response lost")

        with pytest.raises(httpx.ReadError if error_kind == "transport" else ApiError):
            invoke(db, "memory", "llm.chat", request, provider)
        with pytest.raises(ApiError) as error:
            invoke(db, "memory", "llm.chat", request, provider)
        assert error.value.code == ErrorCode.MODEL_INVOCATION_UNCERTAIN
        assert calls == [1]
        assert db.scalar(select(ModelInvocation)).state == "uncertain"


def test_unavailable_memory_service_does_not_run_local_fallback(monkeypatch):
    from lifereel_api.architecture import internal
    from lifereel_api.modules.memory.schemas import MemoryCompileRequest
    from lifereel_api.modules.memory.service import compile_memories

    monkeypatch.setenv("SERVICE_MODE", "distributed")
    monkeypatch.setenv("LIFEREEL_SERVICE", "worker-interview")

    def unavailable(*args, **kwargs):
        raise ApiError(503, ErrorCode.SERVICE_UNAVAILABLE)

    monkeypatch.setattr(internal, "call", unavailable)
    with SessionLocal() as db:
        tenant_id = tenant(db)
        with pytest.raises(ApiError) as error:
            compile_memories(db, tenant_id, MemoryCompileRequest(subject_id=uuid4()))
        assert error.value.code == ErrorCode.SERVICE_UNAVAILABLE

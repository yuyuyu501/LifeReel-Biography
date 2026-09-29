"""Runs inside the QA interview container against a synthetic provider."""

import json
import time
from uuid import uuid4

import httpx
from sqlalchemy import select

from lifereel_api.architecture.internal import call
from lifereel_api.architecture.metadata import register_models
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.billing.models import UsageEvent
from lifereel_api.modules.billing.usage import _context
from lifereel_api.modules.identity.models import Tenant

register_models()
with SessionLocal() as db:
    tenant = db.scalar(select(Tenant.id).order_by(Tenant.created_at))
reference = str(uuid4())
token = _context.set((tenant, "interview", reference))
try:
    payload = {
        "task": "interview",
        "model": "synthetic-model",
        "messages": [{"role": "user", "content": "synthetic input"}],
        "json_output": True,
        "parse_json": True,
    }
    first = call("model-gateway", "llm.chat", tenant, payload)
    assert first == {"output": {"synthetic": True}}
    assert call("model-gateway", "llm.chat", tenant, payload) == first
    payload["messages"][0]["content"] = "simulate-disconnect"
    try:
        call("model-gateway", "llm.chat", tenant, payload)
        raise AssertionError("Disconnect was ignored")
    except httpx.RequestError:
        pass
    try:
        call("model-gateway", "llm.chat", tenant, payload)
        raise AssertionError("Uncertain request was repeated")
    except ApiError as exc:
        assert exc.code == ErrorCode.MODEL_INVOCATION_UNCERTAIN
    with httpx.Client(trust_env=False) as client:
        counts = client.get("http://lifereel-servicesqa-provider:8766/counts").json()
    assert counts == {"success": 1, "disconnect": 1}, counts
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            receipts = list(db.scalars(select(UsageEvent).where(UsageEvent.reference == reference)))
        if len(receipts) == 2:
            assert {receipt.status for receipt in receipts} == {"succeeded", "failed"}
            assert all(receipt.tenant_id == tenant for receipt in receipts)
            break
        time.sleep(1)
    else:
        raise AssertionError("Usage outbox did not reach billing")
    print(
        json.dumps(
            {
                "gateway_replay": "passed",
                "uncertain_request_fenced": "passed",
                "usage_delivered_once": "passed",
                "provider_calls": counts,
            }
        )
    )
finally:
    _context.reset(token)

"""Authenticated, allowlisted internal operations. No dynamic imports from requests."""

import hashlib
import hmac
import time
from importlib import import_module
from uuid import UUID

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lifereel_api.architecture.topology import ROUTERS, service_name, service_url
from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode

HANDLERS = {
    "memory": "lifereel_api.modules.memory.internal",
    "script": "lifereel_api.modules.script.internal",
    "media": "lifereel_api.modules.evidence.internal",
    "billing": "lifereel_api.modules.billing.internal",
    "model-gateway": "lifereel_api.providers.internal",
    "identity": "lifereel_api.modules.identity.internal",
    "interview": "lifereel_api.modules.interview.internal",
    "tasks": "lifereel_api.modules.jobs.internal",
}
CALLERS = frozenset(ROUTERS) | {"worker-interview", "worker-media"}


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    payload: dict = Field(default_factory=dict)
    usage_operation: str | None = Field(default=None, max_length=80)
    usage_reference: str | None = Field(default=None, max_length=100)


def signature(source, timestamp, path, body):
    secret = get_settings().api_access_key
    if not secret:
        raise ApiError(503, ErrorCode.API_KEY_NOT_CONFIGURED)
    key = hmac.new(
        secret.encode(), ("lifereel-service-v1:" + source).encode(), hashlib.sha256
    ).digest()
    return hmac.new(
        key, timestamp.encode() + b"\n" + path.encode() + b"\n" + body, hashlib.sha256
    ).hexdigest()


def call(target, operation, tenant_id, payload, *, timeout=900):
    from lifereel_api.modules.billing.usage import current_context

    context = current_context()
    source = service_name()
    if source not in CALLERS:
        raise RuntimeError("INTERNAL_CALLER_NOT_CONFIGURED")
    envelope = Envelope(tenant_id=tenant_id, payload=payload)
    if context:
        if context[0] != tenant_id:
            raise ApiError(403, ErrorCode.AUTH_MEMBERSHIP_MISSING)
        envelope.usage_operation, envelope.usage_reference = context[1:]
    body = envelope.model_dump_json().encode()
    path = f"/internal/v1/{operation}"
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-Service-Name": source,
        "X-Service-Time": timestamp,
        "X-Service-Signature": signature(source, timestamp, path, body),
    }
    try:
        # Never retry an uncertain mutation/model invocation or fall back to local code.
        with httpx.Client(
            trust_env=False, timeout=httpx.Timeout(timeout, connect=5, pool=5)
        ) as client:
            response = client.post(service_url(target) + path, content=body, headers=headers)
    except httpx.RequestError:
        raise ApiError(503, ErrorCode.SERVICE_UNAVAILABLE) from None
    if not response.is_success:
        try:
            detail = response.json()
            code = ErrorCode(detail.get("error", {}).get("code", "SERVICE_UNAVAILABLE"))
        except (KeyError, ValueError):
            detail = {}
            code = ErrorCode.SERVICE_UNAVAILABLE
        if detail.get("provider_error"):
            from lifereel_api.providers.rpc import raise_provider_error

            raise_provider_error(detail["provider_error"])
        raise ApiError(response.status_code, code)
    return response.json()


def committed_read(db):
    """Do not silently commit a caller's partially built business transaction."""
    if db.new or db.deleted or any(db.is_modified(row) for row in db.dirty):
        raise RuntimeError("INTERNAL_CALL_REQUIRES_COMMITTED_INPUT")
    db.expire_all()


def router_for(owner):
    router = APIRouter()
    module = import_module(HANDLERS[owner])

    @router.post("/internal/v1/{operation}", include_in_schema=False)
    async def dispatch(operation: str, request: Request):
        from starlette.concurrency import run_in_threadpool

        source = request.headers.get("x-service-name", "")
        stamp = request.headers.get("x-service-time", "")
        supplied = request.headers.get("x-service-signature", "")
        if source not in CALLERS or not stamp.isdecimal() or abs(time.time() - int(stamp)) > 90:
            raise ApiError(401, ErrorCode.API_KEY_INVALID)
        body = await request.body()
        if len(body) > 180_000_000:
            raise ApiError(413, ErrorCode.REQUEST_VALIDATION_FAILED)
        if not hmac.compare_digest(signature(source, stamp, request.url.path, body), supplied):
            raise ApiError(401, ErrorCode.API_KEY_INVALID)
        entry = module.OPERATIONS.get(operation)
        if entry is None or source not in entry[0]:
            raise ApiError(403, ErrorCode.AUTH_READ_ONLY)
        try:
            envelope = Envelope.model_validate_json(body)
            if hasattr(module, "validate"):
                envelope.payload = module.validate(operation, envelope.payload)
        except (ValidationError, ValueError, TypeError):
            raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED) from None

        def execute():
            from lifereel_api.modules.billing.usage import _context

            context = (
                None
                if not envelope.usage_operation
                else (
                    envelope.tenant_id,
                    envelope.usage_operation,
                    envelope.usage_reference,
                )
            )
            token = _context.set(context)
            try:
                with SessionLocal() as db:
                    if owner == "model-gateway" and operation == "llm.chat":
                        from lifereel_api.providers.invocations import invoke
                        return invoke(db, source, operation, envelope, entry[1])
                    result = entry[1](db, envelope.tenant_id, envelope.payload)
                    db.commit()
                    return result
            finally:
                _context.reset(token)

        try:
            return await run_in_threadpool(execute)
        except ValidationError:
            raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED) from None
        except ApiError:
            raise
        except Exception as exc:
            if owner == "model-gateway":
                from lifereel_api.providers.rpc import provider_error

                detail = provider_error(exc)
                if detail:
                    return JSONResponse({"provider_error": detail}, status_code=502)
            raise

    return router

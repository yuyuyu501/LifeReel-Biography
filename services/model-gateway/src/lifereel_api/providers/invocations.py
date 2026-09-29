"""A retry can retrieve an answer, but cannot repeat an uncertain paid call."""

import hashlib
import json
from uuid import uuid5

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.providers.models import ModelInvocation
from lifereel_api.providers.rpc import provider_error, raise_provider_error


def invoke(db, source, operation, envelope, function):
    settings = get_settings()
    scope = hashlib.sha256((settings.openai_compatible_api_key or "").encode()).hexdigest()
    canonical = json.dumps(
        {
            "source": source,
            "operation": operation,
            "reference": envelope.usage_reference,
            "usage": envelope.usage_operation,
            "payload": envelope.payload,
            "provider": settings.openai_compatible_base_url,
            "credential_scope": scope,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    invocation_id = uuid5(envelope.tenant_id, digest)
    with execution_lock(db, invocation_id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.MODEL_INVOCATION_UNCERTAIN)
        row = db.get(ModelInvocation, invocation_id)
        if row:
            if row.tenant_id != envelope.tenant_id or row.request_digest != digest:
                raise ApiError(403, ErrorCode.AUTH_READ_ONLY)
            if row.state == "completed":
                return row.response
            if row.state == "rejected" and row.response:
                raise_provider_error(row.response)
            raise ApiError(409, ErrorCode.MODEL_INVOCATION_UNCERTAIN)
        row = ModelInvocation(
            id=invocation_id,
            tenant_id=envelope.tenant_id,
            operation=operation,
            request_digest=digest,
            state="running",
        )
        db.add(row)
        db.commit()
        try:
            result = function(db, envelope.tenant_id, envelope.payload)
            row.response, row.state = result, "completed"
            db.commit()
            return result
        except Exception as exc:
            db.rollback()
            row = db.get(ModelInvocation, invocation_id)
            detail = provider_error(exc)
            safe_refusal = isinstance(exc, ApiError) and exc.code in {
                ErrorCode.BILLING_MODEL_UNPRICED,
                ErrorCode.WALLET_INSUFFICIENT_BALANCE,
                ErrorCode.BILLING_USAGE_PENDING,
                ErrorCode.INTERVIEW_LLM_CONFIGURATION_INCOMPLETE,
            }
            if safe_refusal or (
                detail
                and detail.get("kind") == "http"
                and detail.get("status") in {400, 401, 403, 404, 413, 422, 429}
            ):
                # Authentication, budget refusal or explicit provider rejection precede use.
                db.delete(row)
            elif detail and detail.get("kind") == "json":
                row.state, row.response = "rejected", detail
            else:
                row.state = "uncertain"
            db.commit()
            raise

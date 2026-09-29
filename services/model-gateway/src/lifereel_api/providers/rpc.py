"""Typed provider transport; error payloads omit credentials and personal prompts."""

import base64
import json
from uuid import uuid4

import httpx

from lifereel_api.architecture.internal import call
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing.usage import current_context


def model_call(operation, payload):
    context = current_context()
    if context is None:
        raise ApiError(401, ErrorCode.AUTH_REQUIRED)
    return call("model-gateway", operation, context[0], payload, timeout=900)


def encode_bytes(value):
    return base64.b64encode(value).decode("ascii")


def decode_bytes(value):
    return base64.b64decode(value, validate=True)


def audio_call(operation, content, filename, mime_type, options):
    from pathlib import Path

    from lifereel_api.modules.evidence.storage import private_storage

    context = current_context()
    if context is None:
        raise ApiError(401, ErrorCode.AUTH_REQUIRED)
    store = private_storage()
    key = f"service-transit/{context[0]}/{uuid4()}.audio"
    try:
        if isinstance(content, Path):
            with content.open("rb") as stream:
                store.put_file(key, stream)
        else:
            store.put(key, content)
        return model_call(
            operation,
            {"key": key, "filename": Path(filename).name, "mime_type": mime_type, **options},
        )
    finally:
        store.delete(key)


def provider_error(exc):
    from lifereel_api.providers.openai_compatible import ProviderHTTPError, ProviderStreamError
    from lifereel_api.providers.video import VideoProviderError

    if isinstance(exc, VideoProviderError):
        return {
            "kind": "video",
            "code": exc.code,
            "task_id": exc.task_id,
            "provider_status": exc.provider_status,
            "provider_error_code": exc.provider_error_code,
        }
    if isinstance(exc, json.JSONDecodeError):
        return {"kind": "json", "code": "LLM_RESPONSE_JSON_INVALID"}
    if isinstance(exc, ProviderStreamError):
        return {"kind": "stream"}
    if isinstance(exc, httpx.HTTPStatusError):
        return {
            "kind": "http",
            "status": exc.response.status_code,
            "unsupported": isinstance(exc, ProviderHTTPError) and exc.response_format_unsupported,
        }
    if isinstance(exc, httpx.RequestError):
        return {"kind": "transport"}
    return None


def raise_provider_error(data):
    from lifereel_api.providers.openai_compatible import (
        ProviderHTTPError,
        ProviderResponseError,
        ProviderStreamError,
    )
    from lifereel_api.providers.video import VideoProviderError

    if data["kind"] == "video":
        raise VideoProviderError(
            data["code"],
            task_id=data.get("task_id"),
            provider_status=data.get("provider_status"),
            provider_error_code=data.get("provider_error_code"),
        )
    if data["kind"] == "json":
        raise ProviderResponseError(data["code"])
    if data["kind"] == "stream":
        raise ProviderStreamError("LLM_STREAM_INCOMPLETE")
    if data["kind"] == "http":
        request = httpx.Request("POST", "http://model-gateway/internal")
        error = ProviderHTTPError(
            "MODEL_GATEWAY_UPSTREAM_ERROR",
            request=request,
            response=httpx.Response(data["status"], request=request),
        )
        error.response_format_unsupported = bool(data.get("unsupported"))
        raise error
    raise httpx.ReadError("MODEL_GATEWAY_TRANSPORT_UNCERTAIN")

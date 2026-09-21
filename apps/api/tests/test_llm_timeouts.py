"""R01 regressions: fake transport only; no provider network or paid calls."""

import json
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from lifereel_api.core.config import Settings, get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError
from lifereel_api.modules.billing import tokens
from lifereel_api.modules.billing.usage import _context, track_usage
from lifereel_api.modules.memory.structured import MemoryClient
from lifereel_api.providers import openai_compatible as provider


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_min_interval_seconds", 0)
    return provider.OpenAICompatibleClient("https://provider.test/v1", "private-key", "test")


def response(data, status=200, headers=None):
    return httpx.Response(
        status, json=data, headers=headers,
        request=httpx.Request("POST", "https://provider.test/v1/chat/completions"),
    )


def completion(content='{"ok": true}', **extra):
    return {"choices": [{"message": {"content": content}}], **extra}


@pytest.mark.parametrize("operation,task", [
    ("question", "interview"), ("interview", "interview"), ("memory", "memory"),
    ("script", "script"), ("evidence", "vision"), ("video", "video_plan"),
])
def test_task_context_selects_all_four_timeouts(llm, monkeypatch, operation, task):
    settings = get_settings()
    expected = {"connect": 7, "read": 240, "write": 33, "pool": 5}
    for phase, seconds in expected.items():
        monkeypatch.setattr(settings, f"{task}_llm_{phase}_timeout_seconds", seconds)
    monkeypatch.setattr(provider, "record", lambda *a, **k: None)

    def post(*args, **kwargs):
        assert kwargs["timeout"].as_dict() == expected
        return response(completion())

    monkeypatch.setattr(httpx, "post", post)
    token = _context.set((uuid4(), operation, None))
    try:
        assert llm.chat_json("system", "prompt") == {"ok": True}
    finally:
        _context.reset(token)


def test_settings_global_inheritance_and_partial_task_override():
    settings = Settings(_env_file=None, llm_read_timeout_seconds=210,
                        video_plan_llm_read_timeout_seconds=300)
    assert settings.llm_timeouts_for("script") == {
        "connect": 10, "read": 210, "write": 30, "pool": 10,
    }
    assert settings.llm_timeouts_for("video_plan")["read"] == 300
    assert Settings(_env_file=None).llm_timeouts_for("interview")["read"] == 180


def test_task_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("LLM_CONNECT_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("VIDEO_PLAN_LLM_READ_TIMEOUT_SECONDS", "240")
    settings = Settings(_env_file=None)
    assert settings.llm_timeouts_for("video_plan")["read"] == 240
    assert settings.llm_timeouts_for("memory")["connect"] == 12


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), 3601])
@pytest.mark.parametrize("field", ["llm_read_timeout_seconds", "memory_llm_pool_timeout_seconds"])
def test_timeout_settings_reject_disabled_unbounded_or_invalid(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_default_accepts_simulated_108_second_video_plan(llm, monkeypatch):
    calls = []
    elapsed = [0.0]
    # Fake the timer only inside this module, never sleep 108 seconds or call a provider.
    monkeypatch.setattr(provider, "time", type("Clock", (), {"monotonic": lambda: elapsed[0]}))
    monkeypatch.setattr(provider, "record", lambda *a, **k: calls.append((a, k)))
    llm.task = "video_plan"

    def post(*args, **kwargs):
        assert kwargs["timeout"].read > 108.55
        elapsed[0] += 108.55
        return response(completion())

    monkeypatch.setattr(httpx, "post", post)
    assert llm.chat_json("system", "prompt") == {"ok": True}
    assert calls[0][0][3] == 108550


@pytest.mark.parametrize("failure,phase", [
    (httpx.ConnectTimeout, "connect"), (httpx.ReadTimeout, "read"),
    (httpx.WriteTimeout, "write"), (httpx.PoolTimeout, "pool"),
])
def test_timeout_is_not_retried_and_diagnostics_are_safe(
    llm, monkeypatch, caplog, failure, phase,
):
    calls, receipts = [], []

    def post(*args, **kwargs):
        calls.append(1)
        raise failure("private-key PRIVATE-PROMPT raw body https://private-url.test")

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(provider, "record", lambda *a, **k: receipts.append(k))
    with pytest.raises(failure) as caught:
        llm.chat_json("PRIVATE-PROMPT", "user")
    assert len(calls) == 1
    assert caught.value.diagnostic["phase"] == phase
    assert receipts[0]["rejected"] is False
    for private in ("private-key", "PRIVATE-PROMPT", "raw body", "private-url"):
        assert private not in caplog.text + str(caught.value)


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 502, 504])
def test_http_error_keeps_status_and_header_id_without_generic_fallback(
    llm, monkeypatch, caplog, status,
):
    calls, receipts = [], []

    def post(*args, **kwargs):
        calls.append(1)
        return response({"error": {"message": "PRIVATE-PROMPT private-key"}}, status,
                        {"x-request-id": "req-safe-123"})

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(provider, "record", lambda *a, **k: receipts.append(k))
    with pytest.raises(httpx.HTTPStatusError) as caught:
        llm.chat_json("PRIVATE-PROMPT", "user")
    assert len(calls) == 1
    assert caught.value.response.status_code == status
    assert caught.value.diagnostic["request_id"] == "req-safe-123"
    assert receipts[0]["request_id"] == "req-safe-123"
    assert str(status) in receipts[0]["error"]
    assert "PRIVATE-PROMPT" not in caplog.text + str(caught.value)
    assert "private-key" not in caplog.text + str(caught.value)


@pytest.mark.parametrize("error", [
    {"param": "response_format", "code": "unsupported_parameter"},
    {"message": "This model does not support response_format"},
    {"message": "'response_format' is not supported with this model"},
    {"message": "Unknown parameter: response_format"},
])
def test_explicit_json_mode_rejection_allows_exactly_one_fallback(llm, monkeypatch, error):
    calls = []

    def post(*args, **kwargs):
        calls.append(kwargs["json"])
        return response({"error": error}, 400) if len(calls) == 1 else response(completion())

    monkeypatch.setattr(httpx, "post", post)
    assert llm.chat_json("system", "user") == {"ok": True}
    assert len(calls) == 2
    assert "response_format" in calls[0] and "response_format" not in calls[1]


@pytest.mark.parametrize("error", [
    {"message": "response_format must be a valid object"},
    {"param": "response_format", "code": "invalid_parameter"},
    {"message": "unsupported model; response_format must be JSON"},
    {"message": "content filter rejected request"},
])
def test_ambiguous_400_does_not_fallback(llm, monkeypatch, error):
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k:
                        calls.append(1) or response({"error": error}, 400))
    with pytest.raises(httpx.HTTPStatusError):
        llm.chat_json("system", "user")
    assert len(calls) == 1


def test_json_mode_fallback_timeout_does_not_trigger_another_attempt(llm, monkeypatch):
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return response({"error": {"message": "response_format is not supported"}}, 400)
        raise httpx.ReadTimeout("unknown result")

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(httpx.ReadTimeout):
        llm.chat_json("", "")
    assert len(calls) == 2


def test_diagnostics_reject_unsafe_id_and_do_not_persist_body(llm, monkeypatch, caplog):
    receipts = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: response(
        completion("PRIVATE-PROMPT not JSON", id="private-key", usage={
            "prompt_tokens": 10, "completion_tokens": 2,
        }), headers={"x-request-id": "unsafe id with whitespace"},
    ))
    monkeypatch.setattr(provider, "record", lambda *a, **k: receipts.append((a, k)))
    with pytest.raises(provider.ProviderResponseError):
        llm.chat_json("", "")
    assert receipts[0][1]["request_id"] is None
    assert receipts[0][0][2] == {"prompt_tokens": 10, "completion_tokens": 2}
    assert "PRIVATE-PROMPT" not in caplog.text and "private-key" not in caplog.text


@pytest.mark.parametrize("data", [
    [], None, {}, {"choices": []}, {"choices": [None]},
    {"choices": [{"message": None}]}, completion(None), completion([]), completion(""),
    completion("PRIVATE-PROMPT not-json"), completion("[]"), completion("null"),
])
def test_invalid_response_is_explicit_safe_and_recorded_failed(llm, monkeypatch, caplog, data):
    receipts = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: response(data))
    monkeypatch.setattr(provider, "record", lambda *a, **k: receipts.append((a, k)))
    with pytest.raises(provider.ProviderResponseError) as caught:
        llm.chat_json("system", "user")
    assert caught.value.doc == ""
    assert receipts[0][0][1] == "failed"
    assert receipts[0][1]["rejected"] is False
    assert "PRIVATE-PROMPT" not in caplog.text + str(caught.value)


@pytest.mark.parametrize("status", [200, 502])
def test_non_json_http_body_preserves_status(llm, monkeypatch, status):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(
        status, text="<html>PRIVATE-PROMPT</html>", headers={"x-request-id": "gateway-123"},
        request=httpx.Request("POST", "https://provider.test"),
    ))
    expected = provider.ProviderResponseError if status == 200 else httpx.HTTPStatusError
    with pytest.raises(expected) as caught:
        llm.chat_json("system", "user")
    assert caught.value.diagnostic["http_status"] == status
    assert caught.value.diagnostic["request_id"] == "gateway-123"
    assert "PRIVATE-PROMPT" not in str(caught.value)


def test_fenced_json_and_plain_chat_are_compatible(llm, monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: response(completion('```json\n{"ok":true}\n```')),
    )
    assert llm.chat_json("", "") == {"ok": True}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: response(completion("ordinary text")))
    assert llm.chat("", "") == "ordinary text"


def test_memory_inheritance_and_image_calls_select_task_without_usage_context(llm, monkeypatch):
    seen = []
    monkeypatch.setattr(get_settings(), "memory_llm_read_timeout_seconds", 201)
    monkeypatch.setattr(get_settings(), "vision_llm_read_timeout_seconds", 202)

    def post(*args, **kwargs):
        seen.append(kwargs["timeout"].read)
        return response(completion(json.dumps({
            "claim_text": "test", "claim_type": "recollection", "confidence": 0.9,
        })))

    monkeypatch.setattr(httpx, "post", post)
    MemoryClient("https://provider.test", "key", "test", stage="claim").chat_json("", "")
    llm.analyze_images("", "", [("image/png", b"synthetic")])
    assert seen == [201, 202]


@pytest.mark.parametrize("failure", [httpx.ConnectTimeout, httpx.ReadTimeout,
                                      httpx.WriteTimeout, httpx.PoolTimeout])
def test_memory_real_provider_chain_never_retries_timeouts(llm, monkeypatch, failure):
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        raise failure("private-key PRIVATE-PROMPT")

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(ApiError) as caught:
        MemoryClient(llm.base_url, llm.api_key, llm.model, stage="claim").chat_json("", "")
    assert len(calls) == 1
    assert caught.value.diagnostic["task"] == "memory"
    assert caught.value.diagnostic["attempt"] == 1


@pytest.mark.parametrize("extra,reason", [
    ({"prompt_tokens_details": {"audio_tokens": 2}}, "unsupported_usage_category"),
    ({"cache_creation_input_tokens": 2}, "unsupported_usage_category"),
    ({"cache_creation_input_tokens": -1}, "unsupported_usage_category"),
    ({"prompt_tokens_details": {"audio_tokens": "2"}}, "unsupported_usage_category"),
    ({"prompt_tokens_details": {"cached_tokens": -1}}, "missing_or_invalid_usage"),
    ({"prompt_tokens_details": {"cached_tokens": "1"}}, "missing_or_invalid_usage"),
    ({"prompt_tokens_details": {"cached_tokens": True}}, "missing_or_invalid_usage"),
    ({"prompt_tokens_details": [1]}, "invalid_usage"),
    ({"prompt_tokens": "10"}, "missing_or_invalid_usage"),
    ({"completion_tokens": -1}, "missing_or_invalid_usage"),
])
def test_unpriceable_receipt_is_preserved_and_remains_pending(client, monkeypatch, extra, reason):
    monkeypatch.setattr(get_settings(), "billing_text_mode", "tokens")
    client.get("/v1/wallet")
    usage = {"prompt_tokens": 10, "completion_tokens": 2, **extra}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: response(
        completion(id="receipt-unsupported", usage=usage),
    ))

    @track_usage("memory")
    def generate(db, tenant_id):
        return provider.OpenAICompatibleClient(
            "https://ark.cn-beijing.volces.com/api/v3", "test-key", tokens.MODEL,
        ).chat_json("system", "user")

    with SessionLocal() as db:
        assert generate(db, get_settings().default_tenant_id) == {"ok": True}
    event = client.get("/v1/wallet/usage").json()["items"][0]
    assert event["usage"] == usage
    assert event["metering"]["status"] == "pending"
    assert event["metering"]["reason"] == reason
    assert client.get("/v1/wallet").json()["frozen_cents"] == 40
    assert client.get("/v1/wallet/ledger?event=consume").json()["total"] == 0


def test_processing_limits_use_cached_settings_without_reading_environment(monkeypatch):
    from lifereel_api.core.processing_limits import get_processing_limits

    monkeypatch.setattr(get_settings(), "document_extract_max_chars", 12345)
    monkeypatch.setenv("DOCUMENT_EXTRACT_MAX_CHARS", "invalid-if-env-were-read-again")
    assert get_processing_limits().document_extract_max_chars == 12345


@pytest.mark.parametrize("field,maximum", [
    ("document_extract_max_chars", 200_000), ("document_extract_max_pages", 1000),
    ("script_input_max_chars", 200_000),
])
def test_processing_settings_reject_out_of_range(field, maximum):
    for value in (0, -1, maximum + 1):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{field: value})


def test_read_timeout_keeps_pending_hold_and_blocks_new_spending(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_text_mode", "tokens")
    client.get("/v1/wallet")
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        raise httpx.ReadTimeout("unknown result")

    monkeypatch.setattr(httpx, "post", post)

    @track_usage("memory")
    def generate(db, tenant_id):
        return provider.OpenAICompatibleClient(
            "https://ark.cn-beijing.volces.com/api/v3", "test-key", tokens.MODEL,
        ).chat_json("system", "user")

    with SessionLocal() as db, pytest.raises(httpx.ReadTimeout):
        generate(db, get_settings().default_tenant_id)
    assert client.get("/v1/wallet").json()["frozen_cents"] == 40
    event = client.get("/v1/wallet/usage").json()["items"][0]
    assert event["metering"]["status"] == "pending"
    with SessionLocal() as db, pytest.raises(ApiError) as caught:
        generate(db, get_settings().default_tenant_id)
    assert caught.value.code.value == "BILLING_USAGE_PENDING"
    assert len(calls) == 1

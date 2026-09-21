import json
from contextlib import contextmanager

import httpx
import pytest

from lifereel_api.core.config import Settings, get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.provider_diagnostics import provider_error_context
from lifereel_api.modules.memory.structured import MemoryClient
from lifereel_api.providers import openai_compatible as provider


def event(payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return ("data: " + text + "\n\n").encode()


def chunk(content=None, finish=None, **extra):
    return {"id": "completion-123", "choices": [{
        "index": 0, "delta": {"content": content}, "finish_reason": finish,
    }], **extra}


class Body(httpx.SyncByteStream):
    def __init__(self, blocks):
        self.blocks = blocks
        self.closed = False

    def __iter__(self):
        for block in self.blocks:
            if isinstance(block, Exception):
                raise block
            yield block

    def close(self):
        self.closed = True


@pytest.fixture
def streaming(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_stream", True)
    monkeypatch.setattr(get_settings(), "llm_min_interval_seconds", 0)
    calls, receipts = [], []
    monkeypatch.setattr(provider, "record", lambda *a, **k: receipts.append((a, k)))

    def install(blocks, status=200):
        body = Body(blocks)

        @contextmanager
        def stream(method, url, **kwargs):
            calls.append(kwargs)
            response = httpx.Response(
                status, stream=body, headers={"x-request-id": "gateway-123"},
                request=httpx.Request(method, url),
            )
            try:
                yield response
            finally:
                response.close()

        monkeypatch.setattr(httpx, "stream", stream)
        return body

    client = provider.OpenAICompatibleClient("https://provider.test", "private-key", "test")
    return client, install, calls, receipts


def test_stream_assembles_split_utf8_and_preserves_final_usage(streaming):
    client, install, calls, receipts = streaming
    usage = {"prompt_tokens": 10, "completion_tokens": 2,
             "prompt_tokens_details": {"audio_tokens": 1}, "cache_creation_input_tokens": 3}
    raw = (b": heartbeat\r\n\r\n" + event(chunk('{"text":'))
           + event(chunk('"中文"}', "stop"))
           + event({"id": "completion-123", "choices": [], "usage": usage}) + event("[DONE]"))
    body = install([raw[i:i + 7] for i in range(0, len(raw), 7)])
    assert client.chat_json("system", "prompt") == {"text": "中文"}
    assert calls[0]["json"]["stream"] is True
    assert calls[0]["json"]["stream_options"] == {"include_usage": True}
    assert receipts[0][0][2] == usage
    assert receipts[0][0][4] == "completion-123"
    assert body.closed


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.WriteTimeout, httpx.ConnectTimeout,
                                      httpx.PoolTimeout])
def test_stream_timeouts_preserve_headers_and_never_retry(streaming, failure, caplog):
    client, install, calls, receipts = streaming
    body = install([event(chunk("partial")), failure("PRIVATE-PROMPT private-key")])
    with pytest.raises(failure) as caught:
        client.chat_json("system", "prompt")
    assert len(calls) == 1 and body.closed
    assert caught.value.diagnostic["http_status"] == 200
    assert caught.value.diagnostic["request_id"] == "gateway-123"
    assert receipts[0][1]["request_id"] == "completion-123"
    assert receipts[0][1]["rejected"] is False
    assert "PRIVATE-PROMPT" not in caplog.text + str(caught.value)


@pytest.mark.parametrize("blocks", [
    [event(chunk("partial"))],
    [event(chunk("{}", "stop"))],
    [event("[DONE]")],
    [event("PRIVATE-PROMPT not-json")],
    [event({"error": {"message": "PRIVATE-PROMPT"}})],
    [b"data: \xff\n\n"],
    [b"x" * 2_000_001],
    [b"<html>PRIVATE-PROMPT not SSE</html>"],
])
def test_invalid_or_incomplete_stream_is_transport_failure_without_retry(streaming, blocks, caplog):
    _, install, calls, _ = streaming
    body = install(blocks)
    client = MemoryClient("https://provider.test", "key", "test", stage="claim")
    with pytest.raises(ApiError) as caught:
        client.chat_json("system", "prompt")
    assert caught.value.code == ErrorCode.MEMORY_LLM_REQUEST_FAILED
    assert len(calls) == 1 and body.closed
    assert "PRIVATE-PROMPT" not in caplog.text


def test_stream_limit_covers_heartbeats_even_without_newline(streaming, monkeypatch):
    client, install, calls, _ = streaming
    elapsed = iter([0, 0, 601, 602])
    monkeypatch.setattr(provider, "time", type("Clock", (), {"monotonic": lambda: next(elapsed)}))
    install([b": heartbeat without newline"])
    with pytest.raises(provider.ProviderStreamError):
        client.chat_json("", "")
    assert len(calls) == 1


def test_stream_receipt_survives_missing_done(streaming):
    client, install, _, receipts = streaming
    usage = {"prompt_tokens": 10, "completion_tokens": 3}
    install([event(chunk("{}", "stop")), event({"choices": [], "usage": usage})])
    with pytest.raises(provider.ProviderStreamError):
        client.chat_json("", "")
    assert receipts[0][0][1:3] == ("failed", usage)


def test_stream_usage_and_completion_id_survive_later_read_timeout(streaming):
    client, install, calls, receipts = streaming
    usage = {"prompt_tokens": 10, "completion_tokens": 3,
             "prompt_tokens_details": {"audio_tokens": 1}}
    install([event(chunk("{}", "stop")),
             event({"id": "receipt-before-disconnect", "choices": [], "usage": usage}),
             httpx.ReadTimeout("lost response")])
    with pytest.raises(httpx.ReadTimeout):
        client.chat_json("", "")
    assert len(calls) == 1
    assert receipts[0][0][1:3] == ("failed", usage)
    assert receipts[0][1]["request_id"] == "receipt-before-disconnect"
    assert receipts[0][1]["rejected"] is False


def test_large_stream_http_error_body_is_bounded_and_keeps_status(streaming):
    client, install, calls, _ = streaming
    body = install([b"x" * 2_000_001, AssertionError("must stop reading")], status=524)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        client.chat_json("", "")
    assert caught.value.response.status_code == 524
    assert body.closed and len(calls) == 1


def test_successful_stream_without_usage_records_unknown_not_zero(streaming):
    client, install, _, receipts = streaming
    install([event(chunk("{}", "stop")), event("[DONE]")])
    assert client.chat_json("", "") == {}
    assert receipts[0][0][2] == {}


def test_stream_524_is_not_retried_and_exposes_safe_context(streaming):
    client, install, calls, _ = streaming
    install([b"<html>PRIVATE-PROMPT private-key</html>"], status=524)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        client.chat_json("", "")
    wrapper = ApiError(502, ErrorCode.INTERVIEW_LLM_REQUEST_FAILED)
    wrapper.__cause__ = caught.value
    assert provider_error_context(wrapper) == {
        "provider_http_status": 524, "provider_request_id": "gateway-123",
    }
    assert len(calls) == 1


def test_stream_settings_are_opt_in_and_task_override_is_independent():
    settings = Settings(_env_file=None)
    assert settings.llm_stream_for("interview") is False
    settings = Settings(_env_file=None, llm_stream=True, interview_llm_stream=False)
    assert settings.llm_stream_for("interview") is False
    assert settings.llm_stream_for("memory") is True


def test_api_handler_exposes_only_allowlisted_provider_metadata(client):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from lifereel_api.core.errors import install_error_handlers

    app = FastAPI()
    install_error_handlers(app)

    @app.get("/test")
    def fail():
        error = provider.ProviderStreamError("safe-code")
        error.diagnostic = {"http_status": 524, "request_id": "req-123",
                            "body": "PRIVATE-PROMPT", "prompt": "PRIVATE-PROMPT"}
        raise ApiError(502, ErrorCode.INTERVIEW_LLM_REQUEST_FAILED) from error

    with TestClient(app) as isolated:
        result = isolated.get("/test")
    assert result.json()["error"]["context"] == {
        "provider_http_status": 524, "provider_request_id": "req-123",
    }
    assert "PRIVATE-PROMPT" not in result.text


def test_gateway_diagnostic_survives_background_workflow_failure(client, monkeypatch):
    from uuid import UUID

    from test_capacity_dispatch import queued_turn

    from lifereel_api.core.database import SessionLocal
    from lifereel_api.modules.interview.models import InterviewTurnWorkflow
    from lifereel_api.modules.jobs import dispatch
    from lifereel_api.modules.orchestration import service

    workflow, claim = queued_turn(client, monkeypatch)

    def assess(*args):
        original = provider.ProviderStreamError("safe-code")
        original.diagnostic = {"http_status": 524, "request_id": "req-background"}
        raise ApiError(502, ErrorCode.INTERVIEW_LLM_REQUEST_FAILED) from original

    monkeypatch.setattr(service, "_assess_chapter", assess)
    with SessionLocal() as db:
        result = dispatch.execute_claim(db, UUID(claim["job_id"]), UUID(claim["token"]))
        assert result["status"] == "failed"
        row = db.get(InterviewTurnWorkflow, UUID(workflow["id"]))
        diagnostic = row.script_brief["memory_recovery"]["diagnostic"]
        assert diagnostic["provider_http_status"] == 524
        assert diagnostic["provider_request_id"] == "req-background"


def test_stream_timeout_with_receipt_settles_only_once(client, monkeypatch):
    from lifereel_api.core.database import SessionLocal
    from lifereel_api.modules.billing import tokens
    from lifereel_api.modules.billing.usage import track_usage

    monkeypatch.setattr(get_settings(), "llm_stream", True)
    monkeypatch.setattr(get_settings(), "billing_text_mode", "tokens")
    client.get("/v1/wallet")

    @contextmanager
    def stream(method, url, **kwargs):
        usage = {"prompt_tokens": 10000, "completion_tokens": 1000}
        response = httpx.Response(200, stream=Body([
            event(chunk("{}", "stop")),
            event({"id": "receipt-once", "choices": [], "usage": usage}),
            httpx.ReadTimeout("lost DONE"),
        ]), request=httpx.Request(method, url))
        try:
            yield response
        finally:
            response.close()

    monkeypatch.setattr(httpx, "stream", stream)

    @track_usage("memory")
    def generate(db, tenant_id):
        return provider.OpenAICompatibleClient(
            "https://ark.cn-beijing.volces.com/api/v3", "key", tokens.MODEL,
        ).chat_json("", "")

    # Simulate reconciliation receiving the same provider receipt twice, never auto-retry it.
    for _ in range(2):
        with SessionLocal() as db, pytest.raises(httpx.ReadTimeout):
            generate(db, get_settings().default_tenant_id)
    events = client.get("/v1/wallet/usage").json()
    assert events["total"] == 1
    assert events["items"][0]["metering"]["status"] == "settled"
    assert client.get("/v1/wallet").json()["available_cents"] == 1999
    assert client.get("/v1/wallet").json()["frozen_cents"] == 0

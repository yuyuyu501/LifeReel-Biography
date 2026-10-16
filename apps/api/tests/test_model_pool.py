"""Fault injection uses synthetic HTTP/SSE only; never contacts paid providers."""

import json
from contextlib import contextmanager
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from lifereel_api.architecture.internal import Envelope
from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.identity.models import Tenant
from lifereel_api.providers import internal, model_pool
from lifereel_api.providers import openai_compatible as provider
from lifereel_api.providers.invocations import invoke
from lifereel_api.providers.models import ModelInvocation

TENANT = UUID("00000000-0000-0000-0000-000000000001")
SOL = "gpt-6.1-sol"
PRO = "doubao-seed-2-1-pro-260915"
LITE = "doubao-seed-2-1-lite-260915"


@pytest.fixture
def pool(monkeypatch):
    settings = get_settings()
    for name, value in {
        "llm_provider": "openai-compatible",
        "openai_compatible_base_url": "https://cctq.example/v1",
        "openai_compatible_api_key": "cctq-test-key",
        "volcengine_api_key": "volc-test-key",
        "script_llm_model": SOL,
        "llm_min_interval_seconds": 0,
        "llm_model_pool_script": f"cctq:{SOL},volcengine:{PRO},volcengine:{LITE}",
        "script_llm_stream": False,
        "llm_model_pool_max_attempts": 3,
        "llm_model_pool_attempt_seconds": 180,
        "llm_model_pool_interview_review": None,
    }.items():
        monkeypatch.setattr(settings, name, value)
    model_pool._circuits.clear()
    receipts = []
    monkeypatch.setattr(provider, "record", lambda *a, **k: receipts.append((a, k)))
    yield settings, receipts
    model_pool._circuits.clear()


def payload():
    return {
        "task": "script", "model": SOL,
        "messages": [{"role": "user", "content": "synthetic interview"}],
        "json_output": True, "parse_json": True,
    }


def completion(content='{"ok":true}'):
    return {"choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10}}


def transport(monkeypatch, responses):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        reply = responses[len(calls) - 1]
        if isinstance(reply, Exception):
            raise reply
        status, data = reply
        return httpx.Response(status, json=data, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    return calls


def test_primary_success_and_business_insufficiency_do_not_switch(pool, monkeypatch):
    calls = transport(monkeypatch, [(200, completion('{"material_sufficient":false}'))])
    result = internal.chat(None, TENANT, payload())
    assert result["output"] == {"material_sufficient": False}
    assert result["model"] == SOL and not result["fallback_used"]
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [404, 408, 429, 500, 502, 503, 524, "timeout", "json"])
def test_retryable_failures_use_correct_backup_credentials_and_receipts(pool, monkeypatch, failure):
    first = (failure, {}) if isinstance(failure, int) else (
        httpx.ReadTimeout("PRIVATE secret") if failure == "timeout" else (200, completion("oops"))
    )
    calls = transport(monkeypatch, [first, (200, completion())])
    result = internal.chat(None, TENANT, payload())
    assert result["model"] == PRO and result["provider"] == "volcengine"
    assert result["fallback_used"]
    assert [c[1]["json"]["model"] for c in calls] == [SOL, PRO]
    assert calls[1][0].startswith(pool[0].volcengine_api_base_url)
    assert calls[1][1]["headers"]["Authorization"] == "Bearer volc-test-key"
    assert calls[1][1]["json"]["thinking"] == {"type": "disabled"}
    assert [receipt[0][0:2] for receipt in pool[1]] == [(SOL, "failed"), (PRO, "succeeded")]


@pytest.mark.parametrize("status", [400, 401, 403, 409, 413, 422])
def test_terminal_http_errors_never_switch(pool, monkeypatch, status):
    calls = transport(monkeypatch, [(status, {})])
    with pytest.raises(provider.ProviderHTTPError):
        internal.chat(None, TENANT, payload())
    assert len(calls) == 1


@pytest.mark.parametrize("data", [
    {"error": {"code": "content_filter", "message": "PRIVATE secret"}},
    {"error": "blocked by policy PRIVATE secret"},
    {"choices": [{"message": {"refusal": "refused"}}]},
    {"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]},
])
def test_policy_refusal_never_switches_even_in_http_200(pool, monkeypatch, data, caplog):
    calls = transport(monkeypatch, [(200, data)])
    with pytest.raises(provider.ProviderPolicyError):
        internal.chat(None, TENANT, payload())
    assert len(calls) == 1 and "PRIVATE" not in caplog.text


def test_stream_error_200_falls_back_but_stream_policy_is_terminal(pool, monkeypatch):
    pool[0].script_llm_stream = True
    calls = []
    policy = [False]

    @contextmanager
    def stream(method, url, **kwargs):
        model = kwargs["json"]["model"]
        calls.append(model)
        if model == SOL:
            data = [{"error": {"code": "content_filter" if policy[0] else "upstream_error"}}]
        else:
            data = [{"choices": [{"index": 0, "delta": {"content": '{"ok":true}'},
                                   "finish_reason": "stop"}]}]
        body = "".join("data: " + json.dumps(item) + "\n\n" for item in data)
        yield httpx.Response(200, content=body + "data: [DONE]\n\n",
                             request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "stream", stream)
    assert internal.chat(None, TENANT, payload())["model"] == PRO
    policy[0] = True
    with pytest.raises(provider.ProviderPolicyError):
        internal.chat(None, TENANT, payload())
    assert calls == [SOL, PRO, SOL]


def test_stream_content_filter_without_delta_is_terminal(pool, monkeypatch):
    pool[0].script_llm_stream = True
    calls = []

    @contextmanager
    def stream(method, url, **kwargs):
        calls.append(kwargs["json"]["model"])
        body = {"choices": [{"index": 0, "finish_reason": "content_filter", "delta": None}]}
        yield httpx.Response(200, content="data: " + json.dumps(body) + "\n\n",
                             request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "stream", stream)
    with pytest.raises(provider.ProviderPolicyError):
        internal.chat(None, TENANT, payload())
    assert calls == [SOL]


def test_three_candidates_bounded_and_all_failure_preserves_uncertainty(pool, monkeypatch):
    calls = transport(monkeypatch, [httpx.ReadTimeout("lost"), (503, {}), (429, {})])
    with pytest.raises(provider.ProviderHTTPError) as caught:
        internal.chat(None, TENANT, payload())
    assert caught.value.pool_uncertain
    assert [c[1]["json"]["model"] for c in calls] == [SOL, PRO, LITE]
    assert len(caught.value.pool_attempts) == 3


def test_attempt_limit_and_cooldown_skip_failed_primary_then_allow_one_probe(pool, monkeypatch):
    settings = pool[0]
    settings.llm_model_pool_max_attempts = 2
    calls = transport(monkeypatch, [(503, {}), (200, completion()), (503, {}),
                                    (200, completion()), (200, completion()), (200, completion())])
    assert internal.chat(None, TENANT, payload())["model"] == PRO
    assert internal.chat(None, TENANT, payload())["model"] == PRO
    assert internal.chat(None, TENANT, payload())["model"] == PRO
    primary_circuit = next(c for key, c in model_pool._circuits.items() if key[1] == SOL)
    primary_circuit.open_until = 1
    assert internal.chat(None, TENANT, payload())["model"] == SOL
    assert [c[1]["json"]["model"] for c in calls] == [SOL, PRO, SOL, PRO, PRO, SOL]


def test_attempt_budget_and_limit_are_enforced(pool, monkeypatch):
    pool[0].llm_model_pool_max_attempts = 1
    pool[0].llm_model_pool_attempt_seconds = 12
    calls = transport(monkeypatch, [(503, {})])
    with pytest.raises(provider.ProviderHTTPError):
        internal.chat(None, TENANT, payload())
    assert len(calls) == 1 and calls[0][1]["timeout"].read == 12


def test_configuration_rejects_primary_mismatch_and_lite_reviewer(pool):
    pool[0].llm_model_pool_script = f"volcengine:{PRO}"
    with pytest.raises(ApiError):
        internal.chat(None, TENANT, payload())
    pool[0].llm_model_pool_interview_review = f"cctq:{SOL},volcengine:{LITE}"
    with pytest.raises(ValueError, match="qualified"):
        pool[0].model_pool_for("interview_review")


@pytest.mark.parametrize("succeeds", [True, False])
def test_gateway_replay_never_repeats_paid_pool_attempts(pool, monkeypatch, succeeds):
    responses = [(503, {}), (200, completion())] if succeeds else [
        httpx.ReadTimeout("lost"), (429, {}), (429, {}),
    ]
    calls = transport(monkeypatch, responses)
    with SessionLocal() as db:
        tenant = Tenant(name="Synthetic pool", slug=str(uuid4()))
        db.add(tenant)
        db.commit()
        request = Envelope(
            tenant_id=tenant.id, usage_operation="book", usage_reference=str(uuid4()),
            payload=payload(),
        )
        if succeeds:
            first = invoke(db, "book", "llm.chat", request, internal.chat)
            assert invoke(db, "book", "llm.chat", request, internal.chat) == first
            assert first["model"] == PRO and len(calls) == 2
        else:
            with pytest.raises(provider.ProviderHTTPError):
                invoke(db, "book", "llm.chat", request, internal.chat)
            with pytest.raises(ApiError) as caught:
                invoke(db, "book", "llm.chat", request, internal.chat)
            assert caught.value.code == ErrorCode.MODEL_INVOCATION_UNCERTAIN
            assert len(calls) == 3
        row = db.scalar(select(ModelInvocation))
        assert row.state == ("completed" if succeeds else "uncertain")


def test_structured_backup_keeps_schema_and_local_actual_model(pool, monkeypatch):
    calls = transport(monkeypatch, [(503, {}), (200, completion())])
    client = provider.OpenAICompatibleClient.for_task("script")
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    assert client.chat_structured("synthetic", "synthetic", schema) == {"ok": True}
    assert client.last_model_used == PRO
    assert calls[1][1]["json"]["response_format"]["json_schema"]["schema"] == schema


def test_rpc_carries_actual_model_and_policy_refusal(pool, monkeypatch):
    from lifereel_api.architecture import topology
    from lifereel_api.providers import rpc

    monkeypatch.setattr(topology, "is_remote", lambda _: True)
    monkeypatch.setattr(rpc, "model_call", lambda *args: {
        "output": {"ok": True}, "model": PRO, "provider": "volcengine", "fallback_used": True,
    })
    client = provider.OpenAICompatibleClient.for_task("script")
    assert client.chat_json("", "") == {"ok": True}
    assert client.last_model_used == PRO and client.fallback_used
    with pytest.raises(provider.ProviderPolicyError):
        rpc.raise_provider_error(rpc.provider_error(provider.ProviderPolicyError("refused")))

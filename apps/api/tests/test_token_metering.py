from uuid import uuid4

import httpx
import pytest

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError
from lifereel_api.modules.billing import service as billing
from lifereel_api.modules.billing import tokens
from lifereel_api.modules.billing.usage import track_usage
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


@pytest.fixture
def token_mode(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_text_mode", "tokens")
    client.get("/v1/wallet")
    return client


def invoke(monkeypatch, receipt_id, usage, *, content='{"ok":true}'):
    def post(*args, **kwargs):
        assert kwargs["json"]["max_tokens"] == tokens.MAX_OUTPUT
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://model.test"),
            json={"id": receipt_id, "usage": usage, "choices": [{"message": {"content": content}}]},
        )

    monkeypatch.setattr(httpx, "post", post)

    @track_usage("script")
    def generate(db, tenant_id):
        return OpenAICompatibleClient(
            "https://ark.cn-beijing.volces.com/api/v3",
            "secret",
            tokens.MODEL,
        ).chat_json("JSON only", "test")

    with SessionLocal() as db:
        return generate(db, get_settings().default_tenant_id)


def test_official_tiers_cache_and_no_reasoning_double_count():
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 500},
        "completion_tokens_details": {"reasoning_tokens": 80},
    }
    result = tokens.quote(tokens.MODEL, usage)
    assert result["official_cost_nano"] == 680_000
    assert result["retail_nano"] == 1_020_000
    assert (
        tokens.quote(tokens.MODEL, {"prompt_tokens": 32000, "completion_tokens": 0})[
            "input_cny_per_million"
        ]
        == "0.8"
    )
    assert (
        tokens.quote(tokens.MODEL, {"prompt_tokens": 32001, "completion_tokens": 0})[
            "input_cny_per_million"
        ]
        == "1.2"
    )


@pytest.mark.parametrize(
    "usage",
    [
        {},
        {"total_tokens": 10},
        {"prompt_tokens": True, "completion_tokens": 1},
        {"prompt_tokens": -1, "completion_tokens": 1},
        {"prompt_tokens": 1, "completion_tokens": 1, "prompt_tokens_details": {"cached_tokens": 2}},
        {"prompt_tokens": 128001, "completion_tokens": 1},
    ],
)
def test_missing_or_invalid_usage_is_not_zero(usage):
    with pytest.raises(ValueError):
        tokens.quote(tokens.MODEL, usage)


def test_subcent_usage_accumulates_without_minimum_charge(token_mode, monkeypatch):
    usage = {"prompt_tokens": 1000, "completion_tokens": 1000}
    for index in range(3):
        invoke(monkeypatch, f"receipt-{index}", usage)
    wallet = token_mode.get("/v1/wallet").json()
    assert wallet["available_cents"] == 1999
    assert wallet["frozen_cents"] == 0
    assert wallet["token_remainder_nano"] == 2_600_000
    assert token_mode.get("/v1/wallet/ledger?event=consume").json()["total"] == 1


def test_invalid_json_still_retains_and_charges_actual_usage(token_mode, monkeypatch):
    with pytest.raises(ValueError):
        invoke(
            monkeypatch,
            "invalid",
            {"prompt_tokens": 10000, "completion_tokens": 1000},
            content="not JSON",
        )
    wallet = token_mode.get("/v1/wallet").json()
    assert wallet["available_cents"] == 1999
    assert wallet["frozen_cents"] == 0
    event = token_mode.get("/v1/wallet/usage").json()["items"][0]
    assert event["metering"]["status"] == "settled"
    assert event["usage"]["prompt_tokens"] == 10000


@pytest.mark.parametrize("invalid", [None, [], "{}", "{invalid", ""])
def test_followup_validation_retry_meters_each_actual_call(token_mode, monkeypatch, invalid):
    import json

    person = token_mode.post("/v1/persons", json={"display_name": "Metering test"}).json()
    chapter = token_mode.get("/v1/chapters").json()[0]
    session = token_mode.post(
        "/v1/interviews", json={"subject_id": person["id"], "chapter_id": chapter["id"]},
    ).json()
    answered = token_mode.post(
        f"/v1/interviews/{session['id']}/rounds/{session['rounds'][0]['id']}/answer",
        json={"answer_text": "I lived with my father in Quanzhou."},
    )
    assert answered.status_code == 200
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openai-compatible")
    monkeypatch.setattr(settings, "openai_compatible_base_url", "https://ark.cn-beijing.volces.com/api/v3")
    monkeypatch.setattr(settings, "openai_compatible_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_compatible_model", tokens.MODEL)
    monkeypatch.setattr(settings, "interview_llm_model", tokens.MODEL)
    calls = []

    def post(*args, **kwargs):
        calls.append(kwargs["json"])
        content = invalid if len(calls) == 1 else json.dumps({
            "next_question": "Thank you for sharing; you can add more details later.",
            "intent": "meaning",
        })
        return httpx.Response(
            200, request=httpx.Request("POST", "https://model.test"),
            json={
                "id": f"followup-{len(calls)}",
                "usage": {"prompt_tokens": 10000, "completion_tokens": 1000},
                "choices": [{"message": {"content": content}}],
            },
        )

    monkeypatch.setattr(httpx, "post", post)
    result = token_mode.get(f"/v1/interviews/{session['id']}/next-question")
    assert result.status_code == 200, result.text
    assert len(calls) == 2
    events = token_mode.get("/v1/wallet/usage").json()
    assert events["total"] == 2
    assert all(event["operation"] == "question" for event in events["items"])
    assert all(event["metering"]["status"] == "settled" for event in events["items"])
    wallet = token_mode.get("/v1/wallet").json()
    assert wallet["available_cents"] == 1997
    assert wallet["frozen_cents"] == 0
    assert wallet["token_remainder_nano"] == 0


def test_duplicate_receipt_does_not_charge_twice(token_mode, monkeypatch):
    for _ in range(2):
        invoke(monkeypatch, "same", {"prompt_tokens": 10000, "completion_tokens": 1000})
    wallet = token_mode.get("/v1/wallet").json()
    assert wallet["available_cents"] == 1999
    assert wallet["token_remainder_nano"] == 5_000_000
    assert wallet["frozen_cents"] == 0
    assert token_mode.get("/v1/wallet/usage").json()["total"] == 1


def test_missing_receipt_is_pending_not_free(token_mode, monkeypatch):
    invoke(monkeypatch, "unknown", {})
    wallet = token_mode.get("/v1/wallet").json()
    assert wallet["frozen_cents"] == 40
    assert token_mode.get("/v1/wallet/ledger?event=consume").json()["total"] == 0
    assert token_mode.get("/v1/wallet/usage").json()["items"][0]["metering"]["status"] == "pending"


def test_nested_calls_keep_workflow_reference(client, monkeypatch):
    workflow_id = uuid4()

    @track_usage("interview")
    def workflow(db, tenant_id, workflow_id):
        invoke(monkeypatch, "nested", {"prompt_tokens": 10, "completion_tokens": 1})

    monkeypatch.setattr(get_settings(), "billing_text_mode", "tokens")
    with SessionLocal() as db:
        workflow(db, get_settings().default_tenant_id, workflow_id)
    event = client.get("/v1/wallet/usage").json()["items"][0]
    assert event["operation"] == "script"
    assert event["reference"] == str(workflow_id)


def test_budget_shortage_stops_before_network(token_mode, monkeypatch):
    with SessionLocal() as db:
        billing.reserve(db, get_settings().default_tenant_id, "other", 1990, "video", "test", {})
        db.commit()
    called = []
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: called.append(True))

    @track_usage("question")
    def call(db, tenant_id):
        return OpenAICompatibleClient(
            "https://ark.cn-beijing.volces.com/api/v3",
            "secret",
            tokens.MODEL,
        ).chat("test", "test")

    with SessionLocal() as db, pytest.raises(ApiError) as error:
        call(db, get_settings().default_tenant_id)
    assert error.value.code.value == "WALLET_INSUFFICIENT_BALANCE"
    assert called == []


def test_released_legacy_script_marker_becomes_zero_price(token_mode):
    settings = get_settings()
    settings.billing_text_mode = "per_successful_chapter_update"
    with SessionLocal() as db:
        billing.reserve(db, settings.default_tenant_id, "legacy", 40, "script", "old", {})
        billing.transition(db, settings.default_tenant_id, "legacy", False)
        db.commit()
    settings.billing_text_mode = "tokens"
    with SessionLocal() as db:
        charge = billing.reserve(db, settings.default_tenant_id, "legacy", 0, "script", "new", {})
        assert charge.amount_cents == 0
        billing.transition(db, settings.default_tenant_id, "legacy", True)
        db.commit()
    assert token_mode.get("/v1/wallet").json()["available_cents"] == 2000


def test_receipt_deduplication_across_operations(token_mode, monkeypatch):
    invoke(monkeypatch, "same-call", {"prompt_tokens": 10000, "completion_tokens": 1000})
    from lifereel_api.modules.billing.usage import record

    @track_usage("memory")
    def receipt(db, tenant_id):
        hold = tokens.begin(
            "https://ark.cn-beijing.volces.com/api/v3", tokens.MODEL, (tenant_id, "memory", None)
        )
        record(
            tokens.MODEL,
            "succeeded",
            {"prompt_tokens": 10000, "completion_tokens": 1000},
            1,
            "same-call",
            reservation=hold,
        )

    with SessionLocal() as db:
        receipt(db, get_settings().default_tenant_id)
    wallet = token_mode.get("/v1/wallet").json()
    assert wallet["available_cents"] == 1999
    assert wallet["token_remainder_nano"] == 5_000_000
    assert wallet["frozen_cents"] == 0


def test_pending_receipt_blocks_repeated_network_calls(token_mode, monkeypatch):
    invoke(monkeypatch, "pending", {})
    called = []
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: called.append(True))
    with pytest.raises(ApiError) as error:
        tokens.begin(
            "https://ark.cn-beijing.volces.com/api/v3",
            tokens.MODEL,
            (get_settings().default_tenant_id, "memory", None),
        )
    assert error.value.code.value == "BILLING_USAGE_PENDING"
    assert called == []
    assert token_mode.get("/v1/wallet").json()["frozen_cents"] == 40


def test_settlement_failure_preserves_receipt_and_supports_reconciliation(token_mode, monkeypatch):
    from sqlalchemy import select

    from lifereel_api.modules.billing.models import Charge, UsageEvent
    from lifereel_api.modules.billing.token_admin import reconcile

    original = tokens.settle

    def fail(db, event, hold):
        billing.transition(db, event.tenant_id, hold, False)
        raise RuntimeError("synthetic settlement failure")

    monkeypatch.setattr(tokens, "settle", fail)
    usage = {"prompt_tokens": 10000, "completion_tokens": 1000}
    invoke(monkeypatch, "retained", usage)
    event = token_mode.get("/v1/wallet/usage").json()["items"][0]
    assert event["usage"] == usage
    assert event["metering"]["status"] == "pending"
    assert token_mode.get("/v1/wallet").json()["frozen_cents"] == 40
    monkeypatch.setattr(tokens, "settle", original)
    with SessionLocal() as db:
        hold = db.scalar(select(Charge).where(Charge.kind == "token_hold"))
        result = reconcile(
            db, hold.id, "synthetic", "verified-test-receipt", {"id": "retained", "usage": usage}
        )
        assert result["metering"]["status"] == "settled"
        db.commit()
        row = db.scalar(select(UsageEvent))
        tokens.settle(db, row, hold.business_key)
        db.commit()
        with pytest.raises(ValueError, match="already_resolved"):
            reconcile(db, hold.id, "synthetic", "same", {"id": "retained", "usage": usage})
    wallet = token_mode.get("/v1/wallet").json()
    assert wallet["available_cents"] == 1999
    assert wallet["token_remainder_nano"] == 5_000_000
    assert wallet["frozen_cents"] == 0


def test_confirmed_no_charge_can_release_pending_hold(token_mode, monkeypatch):
    from sqlalchemy import select

    from lifereel_api.modules.billing.models import Charge
    from lifereel_api.modules.billing.token_admin import reconcile

    invoke(monkeypatch, "unknown", {})
    with SessionLocal() as db:
        hold = db.scalar(select(Charge).where(Charge.kind == "token_hold"))
        reconcile(db, hold.id, "synthetic", "provider confirmed no charge", None)
        db.commit()
    assert token_mode.get("/v1/wallet").json()["frozen_cents"] == 0
    invoke(monkeypatch, "next", {"prompt_tokens": 1000, "completion_tokens": 1000})


def test_http_rejection_is_released_but_server_timeout_is_pending(token_mode, monkeypatch):
    @track_usage("question")
    def call(db, tenant_id):
        return OpenAICompatibleClient(
            "https://ark.cn-beijing.volces.com/api/v3",
            "secret",
            tokens.MODEL,
        ).chat("test", "test")

    for status_code in (429, 504):
        monkeypatch.setattr(
            httpx,
            "post",
            lambda *args, status_code=status_code, **kwargs: httpx.Response(
                status_code,
                request=httpx.Request("POST", "https://model.test"),
                json={"error": {"message": "synthetic"}},
            ),
        )
        with SessionLocal() as db, pytest.raises(httpx.HTTPStatusError):
            call(db, get_settings().default_tenant_id)
        expected_frozen = 0 if status_code == 429 else 40
        assert token_mode.get("/v1/wallet").json()["frozen_cents"] == expected_frozen


def test_unknown_model_does_not_reserve_money(token_mode):
    with pytest.raises(ApiError) as error:
        tokens.begin(
            "https://ark.cn-beijing.volces.com/api/v3",
            "unpriced",
            (get_settings().default_tenant_id, "script", None),
        )
    assert error.value.code.value == "BILLING_MODEL_UNPRICED"
    assert token_mode.get("/v1/wallet").json()["frozen_cents"] == 0

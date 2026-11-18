import base64
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from lifereel_api.modules.billing import alipay
from lifereel_api.modules.billing.models import RechargeOrder
from lifereel_api.modules.billing.recharge import review
from lifereel_api.modules.identity.models import Tenant
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.models import utcnow

APP = "2021000000000001"


@pytest.fixture
def online(client, monkeypatch, tmp_path):
    app_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    provider_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = tmp_path / "application.pem"
    public = tmp_path / "alipay.pem"
    private.write_bytes(
        app_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public.write_bytes(
        provider_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    for key, value in {
        "alipay_enabled": True,
        "alipay_app_id": APP,
        "alipay_private_key_path": str(private),
        "alipay_public_key_path": str(public),
        "alipay_seller_id": "2088000000000001",
    }.items():
        monkeypatch.setattr(get_settings(), key, value)
    return client, app_key, provider_key


def create(client, amount=123, request=None, **kwargs):
    response = client.post(
        "/v1/wallet/recharge",
        json={
            "request_id": str(request or uuid4()),
            "amount_cents": amount,
        },
        **kwargs,
    )
    assert response.status_code == 200, response.text
    return response.json()


def signed(key, content):
    return base64.b64encode(
        key.sign(content.encode(), padding.PKCS1v15(), hashes.SHA256())
    ).decode()


def notification(row, **extra):
    return {
        "app_id": APP,
        "out_trade_no": UUID(row["id"]).hex,
        "seller_id": "2088000000000001",
        "trade_no": "202611180000000000001",
        "trade_status": "TRADE_SUCCESS",
        "total_amount": "1.23",
        **extra,
    }


def post_notify(client, key, params):
    return client.post(
        "/v1/wallet/alipay/notify",
        data={
            **params,
            "sign_type": "RSA2",
            "sign": signed(key, alipay.canonical(params)),
        },
    )


def test_checkout_signed_amount_and_order_are_bound_and_creation_never_credits(online):
    client, app_key, _ = online
    request = uuid4()
    row = create(client, request=request)
    again = create(client, request=request)
    assert again["id"] == row["id"]
    assert row["settlement"] == "alipay_page"
    parts = urlparse(row["checkout_url"])
    assert parts.scheme == "https" and parts.netloc == "openapi.alipay.com"
    params = {k: v[0] for k, v in parse_qs(parts.query).items()}
    signature = params.pop("sign")
    app_key.public_key().verify(
        base64.b64decode(signature),
        alipay.canonical(params).encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    biz = json.loads(params["biz_content"])
    assert params["app_id"] == APP and params["method"] == "alipay.trade.page.pay"
    assert biz["out_trade_no"] == UUID(row["id"]).hex and biz["total_amount"] == "1.23"
    assert biz["product_code"] == "FAST_INSTANT_TRADE_PAY"
    assert client.get("/v1/wallet").json()["available_cents"] == 2000
    assert client.get(f"/v1/wallet/recharge/qr?order_id={row['id']}").status_code == 409
    assert (
        client.post(
            f"/v1/wallet/recharge/{row['id']}/report",
            json={
                "payer_reference": "FAKE123456",
            },
        ).status_code
        == 409
    )
    assert client.post(f"/v1/wallet/recharge/{row['id']}/cancel").status_code == 409
    with SessionLocal() as db, pytest.raises(ApiError):
        review(db, UUID(row["id"]), "operator", "SOME_REFERENCE", 123)


def test_verified_callback_credits_exactly_once_without_login_even_when_disabled(
    online, monkeypatch
):
    client, _, provider = online
    row = create(client)
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(get_settings(), "alipay_enabled", False)
    monkeypatch.setattr(get_settings(), "api_access_key", "synthetic-internal-key")
    for _ in range(2):
        result = post_notify(client, provider, notification(row))
        assert result.status_code == 200 and result.text == "success"
    monkeypatch.setattr(get_settings(), "app_env", "test")
    assert client.get("/v1/wallet").json()["available_cents"] == 2123
    entries = client.get("/v1/wallet/ledger?event=recharge").json()
    assert entries["total"] == 1 and entries["items"][0]["title"] == "支付宝充值"


@pytest.mark.parametrize(
    "extra",
    [
        {"app_id": "2021000000000002"},
        {"seller_id": "2088000000000002"},
        {"total_amount": "1.24"},
        {"total_amount": "NaN"},
        {"total_amount": "1.230"},
        {"out_trade_no": uuid4().hex},
        {"trade_no": "bad"},
    ],
)
def test_invalid_business_fields_cannot_credit_even_with_valid_signature(online, extra):
    client, _, provider = online
    row = create(client)
    assert post_notify(client, provider, notification(row, **extra)).status_code == 400
    assert client.get("/v1/wallet").json()["available_cents"] == 2000


def test_forgery_duplicate_fields_and_unpaid_notification_do_not_credit(online):
    client, app_key, provider = online
    row = create(client)
    assert post_notify(client, app_key, notification(row)).status_code == 400
    assert (
        post_notify(client, provider, notification(row, trade_status="WAIT_BUYER_PAY")).text
        == "success"
    )
    assert (
        client.post(
            "/v1/wallet/alipay/notify",
            content="app_id=a&app_id=b",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/wallet/alipay/notify",
            content=b"x" * 65537,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
        ).status_code
        == 413
    )
    assert client.get("/v1/wallet").json()["available_cents"] == 2000


def test_trade_reference_cannot_credit_two_orders(online):
    client, _, provider = online
    first, second = create(client), create(client)
    assert post_notify(client, provider, notification(first)).text == "success"
    assert post_notify(client, provider, notification(second)).status_code == 400
    assert client.get("/v1/wallet").json()["available_cents"] == 2123


def test_query_recovers_missed_callback_and_callback_replay_is_safe(online, monkeypatch):
    client, _, provider = online
    row = create(client)
    calls = []

    def query(order):
        calls.append(order.id)
        data = {"code": "10000", **notification(row)}
        data.pop("seller_id")  # Query is scoped by the signed APPID request.
        return data

    monkeypatch.setattr(alipay, "query_order", query)
    response = client.get(f"/v1/wallet/recharge/{row['id']}")
    assert response.json()["status"] == "credited"
    assert post_notify(client, provider, notification(row)).text == "success"
    assert client.get("/v1/wallet").json()["available_cents"] == 2123
    assert len(calls) == 1


def test_query_cooldown_and_background_reconciliation(online, monkeypatch):
    client, _, _ = online
    row = create(client)
    calls = []

    def query(order):
        calls.append(order.id)
        return {"code": "40004", "sub_code": "ACQ.TRADE_NOT_EXIST"}

    monkeypatch.setattr(alipay, "query_order", query)
    for _ in range(3):
        assert client.get(f"/v1/wallet/recharge/{row['id']}").json()["status"] == "pending"
    assert len(calls) == 1
    with SessionLocal() as db:
        order = db.get(RechargeOrder, UUID(row["id"]))
        order.payment_checked_at = utcnow() - timedelta(seconds=20)
        db.commit()
    monkeypatch.setattr(alipay, "query_order", lambda _: {"code": "10000", **notification(row)})
    alipay.reconcile_pending()
    assert client.get("/v1/wallet").json()["available_cents"] == 2123


def test_raw_query_signature_verification_rejects_tampering_and_duplicates(online):
    _, _, provider = online
    payload = '{ "code": "10000", "trade_status": "TRADE_SUCCESS", "subject": "服务" }'
    response = (
        '{"alipay_trade_query_response":'
        + payload
        + ',"sign":'
        + json.dumps(signed(provider, payload))
        + "}"
    )
    assert alipay.verified_response(response, "alipay.trade.query")["code"] == "10000"
    with pytest.raises(ApiError):
        alipay.verified_response(response.replace("10000", "10001"), "alipay.trade.query")
    with pytest.raises(ValueError):
        alipay.verified_response(response[:-1] + ',"sign":"duplicate"}', "alipay.trade.query")


def test_query_http_transport_signs_request_and_verifies_provider_response(online, monkeypatch):
    import httpx

    client, app_key, provider = online
    row = create(client)
    real_client = httpx.Client

    def handle(request):
        params = {key: value[0] for key, value in parse_qs(request.content.decode()).items()}
        signature = params.pop("sign")
        app_key.public_key().verify(
            base64.b64decode(signature),
            alipay.canonical(params).encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        assert params["method"] == "alipay.trade.query" and params["app_id"] == APP
        assert json.loads(params["biz_content"]) == {"out_trade_no": UUID(row["id"]).hex}
        payload = json.dumps({"code": "10000", **notification(row)}, separators=(",", ":"))
        return httpx.Response(
            200,
            text=(
                '{"alipay_trade_query_response":'
                + payload
                + ',"sign":'
                + json.dumps(signed(provider, payload))
                + "}"
            ),
        )

    monkeypatch.setattr(
        alipay.httpx,
        "Client",
        lambda **kw: real_client(**kw, transport=httpx.MockTransport(handle)),
    )
    assert client.get(f"/v1/wallet/recharge/{row['id']}").json()["status"] == "credited"
    assert client.get("/v1/wallet").json()["available_cents"] == 2123


def test_query_failure_never_credits_or_cancels_an_uncertain_payment(online, monkeypatch):
    client, _, _ = online
    row = create(client)

    def fail_query(_):
        raise ApiError(502, ErrorCode.PAYMENT_QUERY_FAILED)

    monkeypatch.setattr(alipay, "query_order", fail_query)
    assert client.get(f"/v1/wallet/recharge/{row['id']}").status_code == 502
    assert client.get("/v1/wallet").json()["available_cents"] == 2000
    with SessionLocal() as db:
        assert db.get(RechargeOrder, UUID(row["id"])).status == "pending"


def test_legacy_manual_orders_cannot_be_credited_by_callback_and_tenant_isolation(online):
    client, _, provider = online
    row = create(client)
    with SessionLocal() as db:
        order = db.get(RechargeOrder, UUID(row["id"]))
        order.settlement = "manual_review"
        order.alipay_app_id = None
        other = uuid4()
        db.add(Tenant(id=other, name="Other", slug=str(other)))
        db.commit()
    assert post_notify(client, provider, notification(row)).status_code == 400
    assert (
        client.get(
            f"/v1/wallet/recharge/{row['id']}",
            headers={
                "X-Tenant-ID": str(other),
            },
        ).status_code
        == 404
    )
    assert client.get("/v1/wallet").json()["available_cents"] == 2000
    with SessionLocal() as db:
        assert db.scalar(select(RechargeOrder.status)) == "pending"


def test_concurrent_valid_notifications_credit_once_on_postgresql(online):
    from concurrent.futures import ThreadPoolExecutor

    from lifereel_api.core.database import engine

    if engine.dialect.name != "postgresql":
        pytest.skip("Row lock verification requires disposable PostgreSQL")
    client, _, provider = online
    row = create(client)
    params = notification(row)
    params = {
        **params,
        "sign_type": "RSA2",
        "sign": signed(provider, alipay.canonical(params)),
    }

    def deliver(_):
        with SessionLocal() as db:
            alipay.notify(db, params)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(deliver, range(8)))
    assert client.get("/v1/wallet").json()["available_cents"] == 2123
    assert client.get("/v1/wallet/ledger?event=recharge").json()["total"] == 1

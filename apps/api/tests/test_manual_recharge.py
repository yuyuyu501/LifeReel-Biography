from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError
from lifereel_api.modules.billing.models import RechargeOrder
from lifereel_api.modules.billing.recharge import review
from lifereel_api.modules.identity.models import Tenant


@pytest.fixture
def payments(client, monkeypatch, tmp_path):
    image = tmp_path / "qr.png"
    image.write_bytes(b"test-image")
    monkeypatch.setattr(get_settings(), "manual_wechat_enabled", True)
    monkeypatch.setattr(get_settings(), "manual_wechat_qr_path", str(image))
    return client


def create(client, amount=1, key=None, headers=None):
    return client.post(
        "/v1/wallet/recharge",
        json={
            "request_id": str(key or uuid4()),
            "amount_cents": amount,
        },
        headers=headers or {},
    )


def submitted(client, headers=None):
    order = create(client, headers=headers).json()
    response = client.post(
        f"/v1/wallet/recharge/{order['id']}/report",
        json={"payer_reference": "420000TEST123456"},
        headers=headers or {},
    )
    assert response.status_code == 200
    return order


def test_manual_reports_never_credit_and_confirm_is_idempotent(payments):
    order = submitted(payments)
    assert payments.get("/v1/wallet").json()["available_cents"] == 2000
    assert payments.post(f"/v1/wallet/recharge/{order['id']}/confirm").status_code == 404
    for _ in range(2):
        with SessionLocal() as db:
            row = review(db, UUID(order["id"]), "test-operator", "VERIFIED123456", 1)
            db.commit()
            assert row.status == "credited"
    assert payments.get("/v1/wallet").json()["available_cents"] == 2001
    ledger = payments.get("/v1/wallet/ledger?event=recharge").json()
    assert ledger["total"] == 1
    assert ledger["items"][0]["paid_delta"] == 1


def test_create_idempotency_amount_validation_and_limits(payments):
    key = uuid4()
    first = create(payments, key=key)
    assert first.json()["id"] == create(payments, key=key).json()["id"]
    assert create(payments, amount=2, key=key).status_code == 409
    for amount in [0, -1, 20001, 1.5, "1", True]:
        assert create(payments, amount=amount).status_code == 422
    for _ in range(9):
        assert create(payments).status_code == 200
    assert create(payments).status_code == 429
    assert payments.get("/v1/wallet").json()["available_cents"] == 2000


def test_tenant_isolation_and_verified_reference_unique_globally(payments):
    other = uuid4()
    with SessionLocal() as db:
        db.add(Tenant(id=other, name="Other", slug=str(other)))
        db.commit()
    headers = {"X-Tenant-ID": str(other)}
    own = submitted(payments)
    assert (
        payments.post(
            f"/v1/wallet/recharge/{own['id']}/report",
            headers=headers,
            json={"payer_reference": "FAKE123456"},
        ).status_code
        == 404
    )
    assert payments.get("/v1/wallet/recharge/orders", headers=headers).json()["items"] == []
    foreign = submitted(payments, headers)
    with SessionLocal() as db:
        review(db, UUID(own["id"]), "operator", "ONCE123456", 1)
        db.commit()
    with SessionLocal() as db, pytest.raises(ApiError) as exc:
        review(db, UUID(foreign["id"]), "operator", "ONCE123456", 1)
    assert exc.value.code == "RECHARGE_RECEIPT_USED"
    assert payments.get("/v1/wallet", headers=headers).json()["available_cents"] == 2000


def test_cancel_reject_mismatch_and_report_replay(payments, monkeypatch):
    order = create(payments).json()
    assert (
        payments.post(f"/v1/wallet/recharge/{order['id']}/cancel").json()["status"] == "cancelled"
    )
    assert (
        payments.post(
            f"/v1/wallet/recharge/{order['id']}/report", json={"payer_reference": "PAYMENT123"}
        ).status_code
        == 409
    )
    order = submitted(payments)
    assert (
        payments.post(
            f"/v1/wallet/recharge/{order['id']}/report",
            json={"payer_reference": "420000TEST123456"},
        ).status_code
        == 200
    )
    with SessionLocal() as db, pytest.raises(ApiError) as exc:
        review(db, UUID(order["id"]), "operator", "CHECK123", 2)
    assert exc.value.code == "RECHARGE_AMOUNT_MISMATCH"
    with SessionLocal() as db:
        review(db, UUID(order["id"]), "operator", None, None, "未找到对应收款")
        db.commit()
    monkeypatch.setattr(get_settings(), "manual_wechat_enabled", False)
    assert create(payments).status_code == 503
    assert payments.get("/v1/wallet/recharge/qr").status_code == 503
    assert payments.get("/v1/wallet").json()["available_cents"] == 2000
    with SessionLocal() as db:
        assert (
            db.scalar(select(RechargeOrder).where(RechargeOrder.id == UUID(order["id"]))).status
            == "rejected"
        )


def test_qr_requires_auth_in_production(payments, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(get_settings(), "api_access_key", "test-api-key")
    monkeypatch.setattr(get_settings(), "auth_token_secret", "test-auth-secret")
    assert payments.get("/v1/wallet/recharge/qr").status_code == 401


def test_hourly_limit_and_payload_cannot_set_balance(payments):
    response = payments.post(
        "/v1/wallet/recharge",
        json={
            "request_id": str(uuid4()),
            "amount_cents": 1,
            "status": "credited",
            "paid_cents": 10000,
        },
    )
    assert response.status_code == 422
    for _ in range(10):
        order = create(payments).json()
        assert payments.post(f"/v1/wallet/recharge/{order['id']}/cancel").status_code == 200
    assert create(payments).status_code == 429
    assert payments.get("/v1/wallet").json()["paid_cents"] == 0


def test_reports_work_when_new_payments_paused_and_details_are_isolated(payments, monkeypatch):
    order = create(payments).json()
    assert payments.get(f"/v1/wallet/recharge/{order['id']}").json()["status"] == "pending"
    other = uuid4()
    with SessionLocal() as db:
        db.add(Tenant(id=other, name="Other", slug=str(other)))
        db.commit()
    assert (
        payments.get(
            f"/v1/wallet/recharge/{order['id']}", headers={"X-Tenant-ID": str(other)}
        ).status_code
        == 404
    )
    monkeypatch.setattr(get_settings(), "manual_wechat_enabled", False)
    response = payments.post(
        f"/v1/wallet/recharge/{order['id']}/report", json={"payer_reference": "PAID123456"}
    )
    assert response.json()["status"] == "submitted"
    assert payments.get("/v1/wallet").json()["paid_cents"] == 0


def test_customer_history_contains_only_credited_payments(payments):
    pending = create(payments).json()
    submitted_order = submitted(payments)
    cancelled = create(payments).json()
    payments.post(f"/v1/wallet/recharge/{cancelled['id']}/cancel")
    rejected = create(payments).json()
    with SessionLocal() as db:
        review(db, UUID(rejected["id"]), "operator", None, None, "未到账")
        db.commit()
    assert payments.get("/v1/wallet/recharge/orders").json()["total"] == 0
    assert payments.get("/v1/wallet").json()["paid_cents"] == 0
    for _ in range(2):
        with SessionLocal() as db:
            review(db, UUID(pending["id"]), "operator", "ACTUAL123456", 1)
            db.commit()
    history = payments.get("/v1/wallet/recharge/orders").json()
    assert history["total"] == 1
    assert [row["id"] for row in history["items"]] == [pending["id"]]
    assert history["items"][0]["status"] == "credited"
    assert payments.get("/v1/wallet/recharge/orders?page=2").json()["items"] == []
    assert payments.get("/v1/wallet").json()["paid_cents"] == 1
    with SessionLocal() as db:
        assert db.get(RechargeOrder, UUID(submitted_order["id"])).status == "submitted"

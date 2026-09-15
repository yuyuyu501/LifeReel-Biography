from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.models import utcnow
from lifereel_api.modules.auth import sms
from lifereel_api.modules.auth.models import (
    AccountAudit,
    AccountPhone,
    AuthRateLimit,
    SmsChallenge,
    TenantMembership,
    UserAccount,
)
from lifereel_api.modules.auth.security import create_token, hash_password, verify_password
from lifereel_api.modules.billing.models import LedgerEntry, Wallet
from lifereel_api.modules.interview.models import Chapter

PASSWORD = "AccountsTest2026!"
PHONE = "13800138001"


@pytest.fixture
def sms_setup(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "registration_enabled", True)
    monkeypatch.setattr(settings, "auth_token_secret", "test-sms-secret")
    monkeypatch.setattr(settings, "sms_enabled", True)
    monkeypatch.setattr(settings, "sms_sign_name", "Test")
    monkeypatch.setattr(settings, "sms_template_code", "SMS_TEST")
    monkeypatch.setattr(settings, "sms_security_template_code", "SMS_SECURITY_TEST")
    deliveries = []
    monkeypatch.setattr(
        sms, "send_code", lambda phone, code, purpose: deliveries.append((phone, code, purpose))
    )
    return deliveries


def issue(client, deliveries, phone=PHONE, purpose="register"):
    result = client.post("/v1/auth/sms", json={"phone": phone, "purpose": purpose})
    assert result.status_code == 200, result.text
    assert "code" not in result.json()
    return {
        "phone": phone,
        "challenge_id": result.json()["challenge_id"],
        "code": deliveries[-1][1],
    }


def register(client, deliveries, phone=PHONE):
    payload = {**issue(client, deliveries, phone), "display_name": "测试账号", "password": PASSWORD}
    result = client.post("/v1/auth/register", json=payload)
    assert result.status_code == 201, result.text
    return result.json(), payload


def login(client, identifier=PHONE, password=PASSWORD):
    result = client.post("/v1/auth/login", json={"email": identifier, "password": password})
    assert result.status_code == 200, result.text
    return client.cookies.get("lifereel_session")


def age_limits():
    with SessionLocal() as db:
        for row in db.scalars(select(AuthRateLimit)):
            row.resets_at = utcnow() - timedelta(seconds=1)
        db.commit()


def test_phone_registration_is_verified_and_isolated(client, sms_setup):
    result, payload = register(client, sms_setup)
    assert result["is_admin"] is False
    assert result["email"] is None
    assert client.post("/v1/auth/register", json=payload).status_code == 400
    with SessionLocal() as db:
        tenant = UUID(result["tenant_id"])
        wallet = db.get(Wallet, tenant)
        assert wallet.bonus_cents == 2000
        assert (
            db.scalar(select(func.count(LedgerEntry.id)).where(LedgerEntry.tenant_id == tenant))
            == 1
        )
        assert db.scalar(select(func.count(Chapter.id)).where(Chapter.tenant_id == tenant)) == 11
        assert tenant != get_settings().default_tenant_id
        challenge = db.get(SmsChallenge, UUID(payload["challenge_id"]))
        assert challenge.code_hash != payload["code"]
        assert challenge.consumed_at
    login(client)
    assert client.get("/v1/persons").json() == []
    assert client.get("/v1/auth/accounts").status_code == 403
    assert client.get("/v1/auth/accounts/" + result["id"]).status_code == 403
    assert (
        client.post(
            "/v1/auth/accounts",
            json={"email": "x@example.com", "password": PASSWORD, "display_name": "X"},
        ).status_code
        == 403
    )
    age_limits()
    duplicate = {**issue(client, sms_setup), "display_name": "重复", "password": PASSWORD}
    assert client.post("/v1/auth/register", json=duplicate).status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(func.count(UserAccount.id)).where(UserAccount.phone == PHONE)) == 1


def test_registration_no_unverified_email_backdoor(client, sms_setup):
    result = client.post(
        "/v1/auth/register",
        json={"email": "bypass@example.com", "password": PASSWORD, "display_name": "bypass"},
    )
    assert result.status_code == 422
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count(UserAccount.id)).where(UserAccount.email == "bypass@example.com")
            )
            == 0
        )


def test_sms_failure_and_missing_configuration_create_no_challenge(client, sms_setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "sms_enabled", False)
    response = client.post("/v1/auth/sms", json={"phone": PHONE, "purpose": "register"})
    assert response.status_code == 503
    monkeypatch.setattr(get_settings(), "sms_enabled", True)

    def fail(*args):
        raise ApiError(502, ErrorCode.SMS_SEND_FAILED)

    monkeypatch.setattr(sms, "send_code", fail)
    assert (
        client.post("/v1/auth/sms", json={"phone": PHONE, "purpose": "register"}).status_code == 502
    )
    with SessionLocal() as db:
        assert db.scalar(select(func.count(SmsChallenge.id))) == 0


def test_sms_cooldown_all_purposes_and_invalid_phone(client, sms_setup):
    issue(client, sms_setup)
    assert (
        client.post("/v1/auth/sms", json={"phone": PHONE, "purpose": "reset_password"}).status_code
        == 429
    )
    assert (
        client.post("/v1/auth/sms", json={"phone": "1234", "purpose": "register"}).status_code
        == 422
    )
    assert len(sms_setup) == 1


def test_registration_template_is_not_used_for_account_recovery(client, sms_setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "sms_reset_template_code", None)
    monkeypatch.setattr(get_settings(), "sms_security_template_code", None)
    response = client.post("/v1/auth/sms", json={"phone": PHONE, "purpose": "reset_password"})
    assert response.status_code == 503
    assert sms_setup == []


def test_client_ip_header_is_only_trusted_from_private_proxy():
    from starlette.requests import Request

    from lifereel_api.modules.auth.throttle import client_address

    request = Request(
        {"type": "http", "client": ("127.0.0.1", 1234), "headers": [(b"x-real-ip", b"192.0.2.12")]}
    )
    assert client_address(request) == "127.0.0.1"
    request.state.internal_access = True
    assert client_address(request) == "192.0.2.12"


def test_sms_wrong_code_locks_expiry_and_purpose_binding(client, sms_setup):
    payload = issue(client, sms_setup)
    wrong = "000000" if payload["code"] != "000000" else "999999"
    registration = {**payload, "password": PASSWORD, "display_name": "X"}
    assert (
        client.post("/v1/auth/password/reset", json={**payload, "password": PASSWORD}).status_code
        == 400
    )
    for _ in range(5):
        assert (
            client.post("/v1/auth/register", json={**registration, "code": wrong}).status_code
            == 400
        )
    assert client.post("/v1/auth/register", json=registration).status_code == 429
    age_limits()
    fresh = issue(client, sms_setup)
    with SessionLocal() as db:
        db.get(SmsChallenge, UUID(fresh["challenge_id"])).expires_at = utcnow() - timedelta(
            seconds=1
        )
        db.commit()
    assert (
        client.post(
            "/v1/auth/register", json={**fresh, "password": PASSWORD, "display_name": "X"}
        ).json()["error"]["code"]
        == "SMS_CODE_EXPIRED"
    )


def test_resend_invalidates_old_code_and_phone_binding(client, sms_setup):
    old = issue(client, sms_setup)
    age_limits()
    new = issue(client, sms_setup)
    assert (
        client.post(
            "/v1/auth/register", json={**old, "password": PASSWORD, "display_name": "X"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/auth/register",
            json={**new, "phone": "13800138002", "password": PASSWORD, "display_name": "X"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/auth/register", json={**new, "password": PASSWORD, "display_name": "X"}
        ).status_code
        == 201
    )


def test_reset_password_invalidates_existing_session(client, sms_setup):
    user, _ = register(client, sms_setup)
    old_cookie = login(client)
    age_limits()
    code = issue(client, sms_setup, purpose="reset_password")
    assert (
        client.post(
            "/v1/auth/password/reset", json={**code, "password": "NewPassword123!"}
        ).status_code
        == 204
    )
    client.cookies.set("lifereel_session", old_cookie)
    assert client.get("/v1/auth/me").status_code == 401
    client.cookies.clear()
    login(client, password="NewPassword123!")
    assert client.get("/v1/auth/me").json()["id"] == user["id"]


def test_profile_password_and_logout_invalidate_sessions(client, sms_setup):
    register(client, sms_setup)
    login(client)
    assert (
        client.patch("/v1/auth/me", json={"display_name": "新称呼"}).json()["display_name"]
        == "新称呼"
    )
    assert client.patch("/v1/auth/me", json={"display_name": "  "}).status_code == 422
    assert (
        client.post(
            "/v1/auth/password",
            json={"current_password": "WrongPassword!", "password": "NewPassword123!"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/auth/password", json={"current_password": PASSWORD, "password": "NewPassword123!"}
        ).status_code
        == 204
    )
    assert client.get("/v1/auth/me").status_code == 401
    client.cookies.clear()
    token = login(client, password="NewPassword123!")
    client.post("/v1/auth/logout")
    client.cookies.set("lifereel_session", token)
    assert client.get("/v1/auth/me").status_code == 401


def test_phone_change_does_not_enable_welcome_bonus_farming(client, sms_setup):
    register(client, sms_setup)
    login(client)
    new_phone = "13800138002"
    code = issue(client, sms_setup, new_phone, "bind_phone")
    assert (
        client.put("/v1/auth/phone", json={**code, "current_password": PASSWORD}).status_code == 204
    )
    assert client.get("/v1/auth/me").status_code == 401
    client.cookies.clear()
    login(client, new_phone)
    age_limits()
    old_phone_code = issue(client, sms_setup)
    assert (
        client.post(
            "/v1/auth/register",
            json={**old_phone_code, "password": PASSWORD, "display_name": "duplicate"},
        ).status_code
        == 409
    )
    with SessionLocal() as db:
        assert db.scalar(select(func.count(AccountPhone.phone))) == 2
        assert db.scalar(select(func.count(LedgerEntry.id))) == 1


def test_self_delete_preserves_billing_and_prevents_reactivation(client, sms_setup):
    user, _ = register(client, sms_setup)
    login(client)
    age_limits()
    code = issue(client, sms_setup, purpose="delete_account")
    result = client.request(
        "DELETE",
        "/v1/auth/me",
        json={
            "current_password": PASSWORD,
            "challenge_id": code["challenge_id"],
            "code": code["code"],
        },
    )
    assert result.status_code == 204, result.text
    assert client.get("/v1/auth/me").status_code == 401
    with SessionLocal() as db:
        deleted = db.get(UserAccount, UUID(user["id"]))
        assert deleted.deleted_at and not deleted.is_active
        assert db.get(Wallet, UUID(user["tenant_id"])).bonus_cents == 2000
        assert db.scalar(select(func.count(LedgerEntry.id))) == 1


def make_admin(client):
    with SessionLocal() as db:
        user = UserAccount(
            email="admin@example.com",
            display_name="Admin",
            password_hash=hash_password(PASSWORD),
            is_admin=True,
        )
        db.add(user)
        db.flush()
        db.add(TenantMembership(user_id=user.id, tenant_id=get_settings().default_tenant_id))
        db.commit()
        user_id = str(user.id)
    login(client, "admin@example.com")
    return user_id


def test_admin_crud_role_protection_and_audit(client, sms_setup):
    admin_id = make_admin(client)
    created = client.post(
        "/v1/auth/accounts",
        json={"email": "managed@example.com", "display_name": "Managed", "password": PASSWORD},
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    assert "password_hash" not in created.json()
    assert client.get(f"/v1/auth/accounts/{user_id}").status_code == 200
    assert client.get("/v1/auth/accounts?q=managed").json()["total"] == 1
    assert client.get("/v1/auth/accounts?q=%").json()["total"] == 0
    for key in ("is_admin", "tenant_id", "phone"):
        assert client.patch(f"/v1/auth/accounts/{user_id}", json={key: True}).status_code == 422
    update = client.patch(
        f"/v1/auth/accounts/{user_id}",
        json={"is_active": False, "display_name": "Updated", "password": "UpdatedPass123!"},
    )
    assert update.status_code == 200
    assert client.get("/v1/auth/accounts?state=inactive").json()["total"] == 1
    assert client.delete(f"/v1/auth/accounts/{admin_id}").status_code == 403
    assert (
        client.patch(f"/v1/auth/accounts/{admin_id}", json={"is_active": False}).status_code == 403
    )
    assert client.delete(f"/v1/auth/accounts/{user_id}").status_code == 204
    assert client.get(f"/v1/auth/accounts/{user_id}").status_code == 404
    with SessionLocal() as db:
        audits = db.scalars(select(AccountAudit).where(AccountAudit.user_id == UUID(user_id))).all()
        assert len(audits) == 3
        assert "UpdatedPass123!" not in str([a.changes for a in audits])
        assert verify_password("UpdatedPass123!", db.get(UserAccount, UUID(user_id)).password_hash)


def test_disabled_account_and_changed_role_block_old_cookie(client, sms_setup):
    user, _ = register(client, sms_setup)
    old = login(client)
    client.cookies.clear()
    make_admin(client)
    assert (
        client.patch(f"/v1/auth/accounts/{user['id']}", json={"is_active": False}).status_code
        == 200
    )
    assert (
        client.patch(f"/v1/auth/accounts/{user['id']}", json={"is_active": True}).status_code == 200
    )
    client.cookies.clear()
    client.cookies.set("lifereel_session", old)
    assert client.get("/v1/auth/me").status_code == 401


def test_cannot_delete_account_with_money_or_outstanding_debt(client, sms_setup):
    admin_id = make_admin(client)
    created = client.post(
        "/v1/auth/accounts",
        json={"email": "money@example.com", "display_name": "Money", "password": PASSWORD},
    ).json()
    with SessionLocal() as db:
        membership = db.scalar(
            select(TenantMembership).where(TenantMembership.user_id == UUID(created["id"]))
        )
        wallet = db.get(Wallet, membership.tenant_id)
        wallet.paid_cents = -12
        db.commit()
    assert client.delete(f"/v1/auth/accounts/{created['id']}").status_code == 409
    assert client.get(f"/v1/auth/accounts/{admin_id}").status_code == 200


def test_forged_admin_claim_and_anonymous_cannot_manage_users(client, sms_setup):
    assert client.get("/v1/auth/accounts").status_code == 401
    user, _ = register(client, sms_setup)
    token = create_token(
        {"sub": user["id"], "tenant_id": user["tenant_id"], "role": "admin", "is_admin": True}
    )
    client.cookies.set("lifereel_session", token)
    assert client.get("/v1/auth/accounts").status_code == 403


def test_provider_uses_sdk_sign_template_and_no_retry(monkeypatch, sms_setup):
    from alibabacloud_dysmsapi20170525.client import Client

    from lifereel_api.modules.auth.sms import configured

    assert configured()
    # Restore the real adapter without sending a network request.
    import importlib

    adapter = importlib.reload(sms)
    captured = []
    monkeypatch.setattr(
        Client,
        "send_sms_with_options",
        lambda self, req, runtime: (
            captured.append((req, runtime)) or SimpleNamespace(body=SimpleNamespace(code="OK"))
        ),
    )
    adapter.send_code(PHONE, "123456", "register")
    req, runtime = captured[0]
    assert req.template_code == "SMS_TEST" and req.sign_name == "Test"
    assert req.template_param == '{"code": "123456"}'
    assert runtime.autoretry is False


def test_login_rate_limit_is_server_side(client, sms_setup):
    for _ in range(15):
        assert (
            client.post("/v1/auth/login", json={"email": PHONE, "password": PASSWORD}).status_code
            == 401
        )
    assert (
        client.post("/v1/auth/login", json={"email": PHONE, "password": PASSWORD}).status_code
        == 429
    )


def test_malformed_claims_return_error_code(client, sms_setup):
    client.cookies.set(
        "lifereel_session", create_token({"sub": "invalid", "tenant_id": str(uuid4())})
    )
    assert client.get("/v1/auth/me").json()["error"]["code"] == "AUTH_SESSION_INVALID"

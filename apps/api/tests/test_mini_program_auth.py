from __future__ import annotations

from uuid import uuid4

import pytest


async def fake_exchange(platform: str, code: str):
    from lifereel_api.modules.auth.mini_program import PlatformCodeIdentity

    return PlatformCodeIdentity(
        platform=platform,
        app_id=f"{platform}-test-app",
        open_id=f"{platform}-open-{code}",
        union_id=f"union-{code}",
    )


def test_mini_program_login_refresh_and_bearer_session(client, monkeypatch) -> None:
    from lifereel_api.modules.auth import mini_program

    from lifereel_api.core.config import get_settings

    monkeypatch.setattr(mini_program, "exchange_code", fake_exchange)
    monkeypatch.setenv("MINI_PROGRAM_ENABLED", "true")
    monkeypatch.setenv("MINI_PROGRAM_REGISTRATION_ENABLED", "true")
    # This test must work without a developer's private .env file.
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "synthetic-mini-program-test-key")
    get_settings.cache_clear()
    try:
        login = client.post(
            "/v1/auth/mini-program/login",
            json={"platform": "wechat", "code": "first", "display_name": "微信测试用户"},
        )
        assert login.status_code == 200
        body = login.json()
        assert body["identity"]["platform"] == "wechat"
        assert body["user"]["display_name"] == "微信测试用户"
        assert body["access_token"]
        assert body["refresh_token"]

        me = client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["id"] == body["user"]["id"]

        refreshed = client.post(
            "/v1/auth/mini-program/refresh",
            json={"refresh_token": body["refresh_token"]},
        )
        assert refreshed.status_code == 200
        refreshed_body = refreshed.json()
        assert refreshed_body["refresh_token"] != body["refresh_token"]

        reused = client.post(
            "/v1/auth/mini-program/refresh",
            json={"refresh_token": body["refresh_token"]},
        )
        assert reused.status_code == 401
        assert reused.json()["error"]["code"] == "MINI_PROGRAM_REFRESH_INVALID"
    finally:
        monkeypatch.delenv("MINI_PROGRAM_ENABLED", raising=False)
        monkeypatch.delenv("MINI_PROGRAM_REGISTRATION_ENABLED", raising=False)
        monkeypatch.delenv("AUTH_TOKEN_SECRET", raising=False)
        get_settings.cache_clear()


def test_mini_program_login_requires_explicit_link_when_registration_disabled(
    client, monkeypatch
) -> None:
    from lifereel_api.modules.auth import mini_program

    from lifereel_api.core.config import get_settings

    monkeypatch.setattr(mini_program, "exchange_code", fake_exchange)
    monkeypatch.setenv("MINI_PROGRAM_ENABLED", "true")
    monkeypatch.setenv("MINI_PROGRAM_REGISTRATION_ENABLED", "false")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/v1/auth/mini-program/login",
            json={"platform": "douyin", "code": uuid4().hex},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "MINI_PROGRAM_NOT_LINKED"
    finally:
        monkeypatch.delenv("MINI_PROGRAM_ENABLED", raising=False)
        monkeypatch.delenv("MINI_PROGRAM_REGISTRATION_ENABLED", raising=False)
        get_settings.cache_clear()


@pytest.fixture
def link_setup(monkeypatch):
    from lifereel_api.modules.auth import mini_program

    from lifereel_api.core.config import get_settings

    monkeypatch.setattr(mini_program, "exchange_code", fake_exchange)
    monkeypatch.setattr(get_settings(), "mini_program_enabled", True)
    monkeypatch.setattr(get_settings(), "mini_program_registration_enabled", False)
    monkeypatch.setattr(get_settings(), "auth_token_secret", "synthetic-link-test-secret")
    from lifereel_api.modules.auth import service

    from lifereel_api.core.database import SessionLocal

    with SessionLocal() as db:
        return service.create_account(db, "跨端账号", "SyntheticLink123!", email="link@example.com")


def link_payload(code="shared"):
    return {
        "platform": "wechat",
        "code": code,
        "email": "link@example.com",
        "password": "SyntheticLink123!",
    }


def test_link_account_preserves_user_tenant_and_password_change_revokes_refresh(client, link_setup):
    from lifereel_api.modules.auth.models import UserAccount
    from sqlalchemy import func, select

    from lifereel_api.core.database import SessionLocal

    result = client.post("/v1/auth/mini-program/link-account", json=link_payload())
    assert result.status_code == 200, result.text
    auth = result.json()
    assert auth["user"]["id"] == str(link_setup.id)
    assert auth["user"]["tenant_id"] == str(link_setup.tenant_id)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    person = client.post("/v1/persons", headers=headers, json={"display_name": "同一位家人"})
    assert person.status_code == 201
    again = client.post(
        "/v1/auth/mini-program/login", json={"platform": "wechat", "code": "shared"}
    )
    assert again.status_code == 200
    assert again.json()["user"]["tenant_id"] == auth["user"]["tenant_id"]
    login = client.post(
        "/v1/auth/login",
        json={
            "email": "link@example.com",
            "password": "SyntheticLink123!",
        },
    )
    assert login.status_code == 200
    assert client.get("/v1/persons").json()[0]["id"] == person.json()["id"]
    assert (
        client.post(
            "/v1/auth/password",
            json={
                "current_password": "SyntheticLink123!",
                "password": "SyntheticChanged456!",
            },
        ).status_code
        == 204
    )
    client.cookies.clear()
    assert client.get("/v1/auth/me", headers=headers).status_code == 401
    for pair in (auth, again.json()):
        response = client.post(
            "/v1/auth/mini-program/refresh",
            json={
                "refresh_token": pair["refresh_token"],
            },
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "MINI_PROGRAM_REFRESH_INVALID"
    with SessionLocal() as db:
        assert db.scalar(select(func.count(UserAccount.id))) == 1


def test_link_account_rejects_wrong_password_and_other_accounts_identity(client, link_setup):
    from lifereel_api.modules.auth import service

    from lifereel_api.core.database import SessionLocal

    wrong = {**link_payload(), "password": "IncorrectPassword!"}
    assert client.post("/v1/auth/mini-program/link-account", json=wrong).status_code == 401
    assert client.post("/v1/auth/mini-program/link-account", json=link_payload()).status_code == 200
    with SessionLocal() as db:
        service.create_account(db, "另一家庭", "OtherSynthetic123!", email="other@example.com")
    other = {**link_payload(), "email": "other@example.com", "password": "OtherSynthetic123!"}
    assert client.post("/v1/auth/mini-program/link-account", json=other).status_code == 409
    # An existing association is retained; it is never silently moved or merged.
    response = client.post(
        "/v1/auth/mini-program/login", json={"platform": "wechat", "code": "shared"}
    )
    assert response.json()["user"]["id"] == str(link_setup.id)


def test_expired_mini_refresh_cannot_extend_a_session(client, link_setup):
    from datetime import timedelta

    from lifereel_api.modules.auth.models import MiniSession
    from sqlalchemy import select

    from lifereel_api.core.database import SessionLocal
    from lifereel_api.core.models import utcnow

    result = client.post("/v1/auth/mini-program/link-account", json=link_payload())
    assert result.status_code == 200
    with SessionLocal() as db:
        db.scalar(select(MiniSession)).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    response = client.post(
        "/v1/auth/mini-program/refresh",
        json={"refresh_token": result.json()["refresh_token"]},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MINI_PROGRAM_REFRESH_INVALID"


def test_link_account_rechecks_disabled_user_after_platform_exchange(
    client, link_setup, monkeypatch
):
    from lifereel_api.modules.auth import mini_program
    from lifereel_api.modules.auth.models import UserAccount

    from lifereel_api.core.database import SessionLocal

    async def disable_during_exchange(platform, code):
        with SessionLocal() as db:
            user = db.get(UserAccount, link_setup.id)
            user.is_active = False
            db.commit()
        return await fake_exchange(platform, code)

    monkeypatch.setattr(mini_program, "exchange_code", disable_during_exchange)
    result = client.post("/v1/auth/mini-program/link-account", json=link_payload())
    assert result.status_code == 401

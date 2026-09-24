from __future__ import annotations

from uuid import uuid4


async def fake_exchange(platform: str, code: str):
    from lifereel_api.modules.auth.mini_program import PlatformCodeIdentity

    return PlatformCodeIdentity(
        platform=platform,
        app_id=f"{platform}-test-app",
        open_id=f"{platform}-open-{code}",
        union_id=f"union-{code}",
    )


def test_mini_program_login_refresh_and_bearer_session(client, monkeypatch) -> None:
    from lifereel_api.core.config import get_settings
    from lifereel_api.modules.auth import mini_program

    monkeypatch.setattr(mini_program, "exchange_code", fake_exchange)
    monkeypatch.setenv("MINI_PROGRAM_ENABLED", "true")
    monkeypatch.setenv("MINI_PROGRAM_REGISTRATION_ENABLED", "true")
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
        get_settings.cache_clear()


def test_mini_program_login_requires_explicit_link_when_registration_disabled(
    client, monkeypatch
) -> None:
    from lifereel_api.core.config import get_settings
    from lifereel_api.modules.auth import mini_program

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

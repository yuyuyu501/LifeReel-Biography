def test_local_login_returns_signed_tenant_session(client, monkeypatch) -> None:
    from lifereel_api.core.config import get_settings
    from lifereel_api.core.database import SessionLocal
    from lifereel_api.modules.auth.models import TenantMembership, UserAccount
    from lifereel_api.modules.auth.security import hash_password

    monkeypatch.setenv("AUTH_TOKEN_SECRET", "test-auth-secret")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            user = UserAccount(
                email="owner@example.com",
                display_name="家庭管理员",
                password_hash=hash_password("StrongPassword2026!"),
            )
            db.add(user)
            db.flush()
            db.add(
                TenantMembership(
                    tenant_id=get_settings().default_tenant_id,
                    user_id=user.id,
                    role="owner",
                )
            )
            db.commit()

        login = client.post(
            "/v1/auth/login",
            json={"email": "owner@example.com", "password": "StrongPassword2026!"},
        )
        assert login.status_code == 200
        assert "lifereel_session" in login.cookies
        assert "access_token" not in login.json()
        me = client.get("/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["role"] == "owner"
        logout = client.post("/v1/auth/logout")
        assert logout.status_code == 204
        assert "lifereel_session" not in client.cookies
    finally:
        monkeypatch.delenv("AUTH_TOKEN_SECRET", raising=False)
        get_settings.cache_clear()


def test_viewer_session_cannot_modify_family_data(client, monkeypatch) -> None:
    from lifereel_api.core.config import get_settings
    from lifereel_api.core.database import SessionLocal
    from lifereel_api.modules.auth.models import TenantMembership, UserAccount
    from lifereel_api.modules.auth.security import create_token, hash_password

    monkeypatch.setenv("AUTH_TOKEN_SECRET", "test-auth-secret")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            user = UserAccount(
                email="viewer@example.com",
                display_name="只读家人",
                password_hash=hash_password("StrongPassword2026!"),
            )
            db.add(user)
            db.flush()
            db.add(
                TenantMembership(
                    tenant_id=get_settings().default_tenant_id,
                    user_id=user.id,
                    role="viewer",
                )
            )
            db.commit()
            token = create_token(
                {
                    "sub": str(user.id),
                    "tenant_id": str(get_settings().default_tenant_id),
                    "role": "viewer",
                }
            )
        client.cookies.set("lifereel_session", token)
        assert client.get("/v1/persons").status_code == 200
        assert (
            client.post("/v1/persons", json={"display_name": "不可创建"}).status_code
            == 403
        )
    finally:
        monkeypatch.delenv("AUTH_TOKEN_SECRET", raising=False)
        get_settings.cache_clear()

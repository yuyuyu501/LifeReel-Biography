def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    providers = client.get("/v1/providers")
    assert providers.status_code == 200
    assert {item["name"] for item in providers.json()} >= {
        "mock-llm",
        "mock-asr",
        "mock-video",
    }


def test_production_mode_requires_api_key(monkeypatch):
    from fastapi.testclient import TestClient

    from lifereel_api.core.config import get_settings
    from lifereel_api.main import app

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "test-auth-secret")
    get_settings.cache_clear()
    try:
        with TestClient(app) as protected_client:
            assert protected_client.get("/v1/chapters").status_code == 401
            assert (
                protected_client.get(
                    "/v1/chapters",
                    headers={
                        "X-API-Key": "test-secret",
                        "X-Tenant-ID": "00000000-0000-0000-0000-000000000001",
                    },
                ).status_code
                == 200
            )
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.delenv("API_ACCESS_KEY", raising=False)
        monkeypatch.delenv("AUTH_TOKEN_SECRET", raising=False)
        get_settings.cache_clear()


def test_ready(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}

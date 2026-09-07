from __future__ import annotations

from uuid import uuid4


def assert_error(response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    assert response.json() == {"error": {"code": code}}
    assert "detail" not in response.json()


def test_business_errors_use_codes(client) -> None:
    assert_error(
        client.post(
            "/v1/auth/login",
            json={"email": "missing@example.com", "password": "NotThePassword2026!"},
        ),
        401,
        "AUTH_INVALID_CREDENTIALS",
    )
    assert_error(
        client.get(f"/v1/persons/{uuid4()}"),
        404,
        "PERSON_NOT_FOUND",
    )


def test_framework_errors_use_codes(client) -> None:
    assert_error(
        client.post("/v1/auth/login", json={"email": "invalid", "password": "short"}),
        422,
        "REQUEST_VALIDATION_FAILED",
    )
    assert_error(client.get("/v1/not-a-real-route"), 404, "ROUTE_NOT_FOUND")
    assert_error(client.delete("/health"), 405, "METHOD_NOT_ALLOWED")

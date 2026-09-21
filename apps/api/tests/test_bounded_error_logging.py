import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from lifereel_api.core.errors import install_error_handlers


def test_response_validation_does_not_log_private_large_input(caplog):
    app = FastAPI()
    install_error_handlers(app)

    class Result(BaseModel):
        text: str = Field(max_length=20)

    secret_document = "PRIVATE-DOCUMENT-CONTENT" * 100_000

    @app.get("/large", response_model=Result)
    def large():
        return {"text": secret_document}

    with TestClient(app, raise_server_exceptions=False) as client:
        with caplog.at_level(logging.ERROR):
            response = client.get("/large")
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "INTERNAL_SERVER_ERROR"}}
    assert "PRIVATE-DOCUMENT" not in caplog.text
    assert len(caplog.text) < 3000
    assert "string_too_long" in caplog.text
    assert "text" in caplog.text
    assert "count=1" in caplog.text


def test_unhandled_exception_keeps_location_without_payload(caplog):
    app = FastAPI()
    install_error_handlers(app)
    secret = "PRIVATE-EXCEPTION-CONTENT" * 100_000

    @app.get("/failure")
    def failure():
        raise ValueError(secret)

    with TestClient(app, raise_server_exceptions=False) as client:
        with caplog.at_level(logging.ERROR):
            response = client.get("/failure")
    assert response.status_code == 500
    assert "PRIVATE-EXCEPTION-CONTENT" not in caplog.text
    assert "ValueError" in caplog.text
    assert "/failure" in caplog.text
    assert len(caplog.text) < 8000

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import status

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode

PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, expected_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), expected_hex)
    except (TypeError, ValueError):
        return False


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_token(payload: dict[str, Any]) -> str:
    settings = get_settings()
    if not settings.auth_token_secret:
        raise RuntimeError("AUTH_TOKEN_SECRET_MISSING")
    now = datetime.now(UTC)
    claims = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.auth_token_minutes)).timestamp()),
    }
    header = _encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _encode(json.dumps(claims, separators=(",", ":")).encode())
    signature = _encode(
        hmac.new(
            settings.auth_token_secret.encode(), f"{header}.{body}".encode(), hashlib.sha256
        ).digest()
    )
    return f"{header}.{body}.{signature}"


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        header, body, signature = token.split(".")
        expected = _encode(
            hmac.new(
                (settings.auth_token_secret or "").encode(),
                f"{header}.{body}".encode(),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("AUTH_SESSION_SIGNATURE_INVALID")
        payload = json.loads(_decode(body))
        UUID(payload["sub"])
        UUID(payload["tenant_id"])
        if int(payload["exp"]) <= int(datetime.now(UTC).timestamp()):
            raise ValueError("AUTH_SESSION_EXPIRED")
        return payload
    except (KeyError, ValueError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, ErrorCode.AUTH_SESSION_INVALID) from exc

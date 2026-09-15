from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from ipaddress import ip_address

from fastapi import Request
from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.models import utcnow
from lifereel_api.modules.auth.models import AuthRateLimit


def client_address(request: Request) -> str:
    # The private web proxy overwrites this header and authenticates using its API key.
    if getattr(request.state, "internal_access", False):
        try:
            return str(ip_address(request.headers.get("x-real-ip", "")))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def limit(scope: str, identity: str, maximum: int, seconds: int) -> None:
    settings = get_settings()
    key = hmac.new(
        (settings.auth_token_secret or "development-throttle").encode(),
        f"{scope}:{identity}".encode(),
        hashlib.sha256,
    ).hexdigest()
    now = utcnow()
    reset = now + timedelta(seconds=seconds)
    # A separate committed transaction keeps failed requests counted across API workers.
    with SessionLocal() as db:
        table = AuthRateLimit.__table__
        insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
        expired = table.c.resets_at <= now
        statement = insert(table).values(key=key, count=1, resets_at=reset)
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.key],
            set_={
                "count": case((expired, 1), else_=table.c.count + 1),
                "resets_at": case((expired, reset), else_=table.c.resets_at),
            },
        ).returning(table.c.count)
        count = db.execute(statement).scalar_one()
        db.execute(delete(AuthRateLimit).where(AuthRateLimit.resets_at < now - timedelta(days=1)))
        db.commit()
    if count > maximum:
        raise ApiError(429, ErrorCode.AUTH_RATE_LIMITED)

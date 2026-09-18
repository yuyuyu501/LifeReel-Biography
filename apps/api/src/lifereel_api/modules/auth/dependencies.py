from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, Header, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import get_db
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.auth.models import TenantMembership, UserAccount
from lifereel_api.modules.auth.security import decode_token

PUBLIC_AUTH_PATHS = {
    "/v1/auth/login",
    "/v1/auth/logout",
    "/v1/auth/register",
    "/v1/auth/registration",
    "/v1/auth/sms",
    "/v1/auth/password/reset",
}


@dataclass(frozen=True)
class AuthContext:
    user_id: UUID | None
    tenant_id: UUID
    role: str


def auth_context(
    request: HTTPConnection,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    lifereel_session: Annotated[str | None, Cookie()] = None,
) -> AuthContext:
    settings = get_settings()
    if request.url.path.startswith("/v1/public/") or request.url.path in PUBLIC_AUTH_PATHS:
        return AuthContext(None, settings.default_tenant_id, "public")
    bearer_token = None
    if (
        request.state.internal_access
        and authorization
        and authorization.lower().startswith("bearer ")
    ):
        bearer_token = authorization.split(" ", 1)[1]
    session_token = lifereel_session or bearer_token
    if session_token:
        payload = decode_token(session_token)
        user_id = UUID(payload["sub"])
        tenant_id = UUID(payload["tenant_id"])
        user = db.get(UserAccount, user_id)
        membership = db.scalar(
            select(TenantMembership).where(
                TenantMembership.user_id == user_id,
                TenantMembership.tenant_id == tenant_id,
            )
        )
        if (
            user is None
            or not user.is_active
            or user.deleted_at
            or membership is None
            or payload.get("version", 0) != user.session_version
        ):
            raise ApiError(status.HTTP_401_UNAUTHORIZED, ErrorCode.AUTH_SESSION_INACTIVE)
        return AuthContext(
            user_id=user_id,
            tenant_id=tenant_id,
            role=membership.role,
        )
    if settings.is_development:
        return AuthContext(
            None, UUID(x_tenant_id) if x_tenant_id else settings.default_tenant_id, "owner"
        )
    if request.state.internal_access and x_tenant_id:
        return AuthContext(None, UUID(x_tenant_id), "worker")
    raise ApiError(status.HTTP_401_UNAUTHORIZED, ErrorCode.AUTH_REQUIRED)


def enforce_write_role(
    request: Request,
    context: Annotated[AuthContext, Depends(auth_context)],
) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.url.path in PUBLIC_AUTH_PATHS or request.url.path.startswith("/v1/public/"):
        return
    if request.url.path.startswith("/v1/auth/") and context.user_id:
        return
    if context.role not in {"owner", "editor", "worker"}:
        raise ApiError(status.HTTP_403_FORBIDDEN, ErrorCode.AUTH_READ_ONLY)

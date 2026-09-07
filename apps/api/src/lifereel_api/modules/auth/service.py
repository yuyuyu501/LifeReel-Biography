from __future__ import annotations

from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.auth.models import TenantMembership, UserAccount
from lifereel_api.modules.auth.schemas import AuthUserRead, LoginResponse
from lifereel_api.modules.auth.security import create_token, verify_password


def login(db: Session, email: str, password: str) -> tuple[LoginResponse, str]:
    user = db.scalar(select(UserAccount).where(UserAccount.email == email.lower()))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise ApiError(status.HTTP_401_UNAUTHORIZED, ErrorCode.AUTH_INVALID_CREDENTIALS)
    membership = db.scalar(select(TenantMembership).where(TenantMembership.user_id == user.id))
    if membership is None:
        raise ApiError(status.HTTP_403_FORBIDDEN, ErrorCode.AUTH_MEMBERSHIP_MISSING)
    auth_user = AuthUserRead(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        tenant_id=membership.tenant_id,
        role=membership.role,
    )
    token = create_token(
        {
            "sub": str(user.id),
            "tenant_id": str(membership.tenant_id),
            "role": membership.role,
        }
    )
    return LoginResponse(expires_in=get_settings().auth_token_minutes * 60, user=auth_user), token


def user_context(db: Session, user_id: UUID, tenant_id: UUID) -> AuthUserRead:
    user = db.get(UserAccount, user_id)
    membership = db.scalar(
        select(TenantMembership).where(
            TenantMembership.user_id == user_id,
            TenantMembership.tenant_id == tenant_id,
        )
    )
    if user is None or membership is None:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, ErrorCode.AUTH_USER_NOT_FOUND)
    return AuthUserRead(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        tenant_id=tenant_id,
        role=membership.role,
    )

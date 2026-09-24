from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Literal
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.models import utcnow
from lifereel_api.modules.auth import service
from lifereel_api.modules.auth.models import (
    MiniSession,
    PlatformIdentity,
    TenantMembership,
    UserAccount,
)
from lifereel_api.modules.auth.security import create_token

Platform = Literal["wechat", "douyin"]


@dataclass(frozen=True)
class PlatformCodeIdentity:
    platform: Platform
    app_id: str
    open_id: str
    union_id: str | None


@dataclass(frozen=True)
class MiniSessionPair:
    access_token: str
    refresh_token: str
    expires_in: int


def _platform_settings(platform: str) -> tuple[Platform, str | None, str | None, str]:
    settings = get_settings()
    if platform == "wechat":
        return (
            "wechat",
            settings.wechat_mini_app_id,
            settings.wechat_mini_app_secret,
            settings.wechat_mini_login_url,
        )
    if platform == "douyin":
        return (
            "douyin",
            settings.douyin_mini_app_id,
            settings.douyin_mini_app_secret,
            settings.douyin_mini_login_url,
        )
    raise ApiError(400, ErrorCode.MINI_PROGRAM_PLATFORM_UNSUPPORTED)


async def exchange_code(platform: str, code: str) -> PlatformCodeIdentity:
    if not get_settings().mini_program_enabled:
        raise ApiError(503, ErrorCode.MINI_PROGRAM_NOT_CONFIGURED)
    selected, app_id, app_secret, endpoint = _platform_settings(platform)
    if not app_id or not app_secret:
        raise ApiError(503, ErrorCode.MINI_PROGRAM_NOT_CONFIGURED)

    params = {
        "appid": app_id,
        "secret": app_secret,
        "code": code,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(
            timeout=get_settings().mini_program_http_timeout_seconds,
            follow_redirects=False,
        ) as client:
            response = await client.get(endpoint, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ApiError(502, ErrorCode.MINI_PROGRAM_CODE_INVALID) from exc

    error_value = payload.get("errcode", payload.get("err_no", 0))
    if error_value not in (0, "0", None):
        raise ApiError(401, ErrorCode.MINI_PROGRAM_CODE_INVALID)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    open_id = data.get("openid") or data.get("open_id")
    if not isinstance(open_id, str) or not open_id.strip():
        raise ApiError(401, ErrorCode.MINI_PROGRAM_CODE_INVALID)
    union_id = data.get("unionid") or data.get("union_id")
    return PlatformCodeIdentity(
        platform=selected,
        app_id=app_id,
        open_id=open_id,
        union_id=union_id if isinstance(union_id, str) else None,
    )


def _hash_refresh(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _new_pair(db: Session, identity: PlatformIdentity, user: UserAccount) -> MiniSessionPair:
    settings = get_settings()
    membership = db.scalar(
        select(TenantMembership).where(
            TenantMembership.user_id == user.id,
            TenantMembership.tenant_id == identity.tenant_id,
        )
    )
    if membership is None:
        raise ApiError(403, ErrorCode.AUTH_MEMBERSHIP_MISSING)
    refresh_token = secrets.token_urlsafe(48)
    session = MiniSession(
        identity_id=identity.id,
        refresh_hash=_hash_refresh(refresh_token),
        session_version=user.session_version,
        expires_at=utcnow() + timedelta(days=settings.mini_refresh_days),
    )
    db.add(session)
    db.flush()
    access_token = create_token(
        {
            "sub": str(user.id),
            "tenant_id": str(identity.tenant_id),
            "role": membership.role,
            "version": user.session_version,
            "token_kind": "mini_program",
            "platform": identity.platform,
        }
    )
    return MiniSessionPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.auth_token_minutes * 60,
    )


def _identity(db: Session, code_identity: PlatformCodeIdentity) -> PlatformIdentity | None:
    return db.scalar(
        select(PlatformIdentity).where(
            PlatformIdentity.platform == code_identity.platform,
            PlatformIdentity.app_id == code_identity.app_id,
            PlatformIdentity.open_id == code_identity.open_id,
        )
    )


def login_or_register(
    db: Session,
    code_identity: PlatformCodeIdentity,
    *,
    display_name: str | None = None,
) -> tuple[UserAccount, PlatformIdentity, MiniSessionPair, bool]:
    identity = _identity(db, code_identity)
    created = False
    if identity is None:
        settings = get_settings()
        if not settings.mini_program_registration_enabled:
            raise ApiError(403, ErrorCode.MINI_PROGRAM_NOT_LINKED)
        name = (display_name or "小程序用户").strip()[:80] or "小程序用户"
        created_user = service.create_account(
            db,
            name,
            secrets.token_urlsafe(32),
            commit=False,
        )
        user = db.get(UserAccount, created_user.id)
        if user is None:
            raise ApiError(500, ErrorCode.INTERNAL_SERVER_ERROR)
        identity = PlatformIdentity(
            user_id=user.id,
            tenant_id=created_user.tenant_id,
            platform=code_identity.platform,
            app_id=code_identity.app_id,
            open_id=code_identity.open_id,
            union_id=code_identity.union_id,
        )
        db.add(identity)
        db.flush()
        created = True
    else:
        user = db.get(UserAccount, identity.user_id)
        if user is None or not user.is_active or user.deleted_at:
            raise ApiError(401, ErrorCode.AUTH_SESSION_INACTIVE)
        if code_identity.union_id and identity.union_id != code_identity.union_id:
            identity.union_id = code_identity.union_id
        db.flush()
    pair = _new_pair(db, identity, user)
    db.commit()
    return user, identity, pair, created


def link(
    db: Session,
    user_id: UUID,
    tenant_id: UUID,
    code_identity: PlatformCodeIdentity,
) -> tuple[PlatformIdentity, MiniSessionPair]:
    user = service.require_user(db, user_id, lock=True)
    existing = _identity(db, code_identity)
    if existing and existing.user_id != user.id:
        db.rollback()
        raise ApiError(409, ErrorCode.AUTH_ACCOUNT_UNAVAILABLE)
    if existing is None:
        identity = PlatformIdentity(
            user_id=user.id,
            tenant_id=tenant_id,
            platform=code_identity.platform,
            app_id=code_identity.app_id,
            open_id=code_identity.open_id,
            union_id=code_identity.union_id,
        )
        db.add(identity)
        db.flush()
    else:
        identity = existing
        if identity.tenant_id != tenant_id:
            db.rollback()
            raise ApiError(403, ErrorCode.AUTH_ACCOUNT_UNAVAILABLE)
    pair = _new_pair(db, identity, user)
    db.commit()
    return identity, pair


def refresh(
    db: Session, refresh_token: str
) -> tuple[UserAccount, PlatformIdentity, MiniSessionPair]:
    session = db.scalar(
        select(MiniSession)
        .where(
            MiniSession.refresh_hash == _hash_refresh(refresh_token),
            MiniSession.revoked_at.is_(None),
        )
        .with_for_update()
    )
    expires_at = session.expires_at.replace(tzinfo=UTC) if session else None
    if session is None or expires_at <= utcnow():
        raise ApiError(401, ErrorCode.MINI_PROGRAM_REFRESH_INVALID)
    identity = db.get(PlatformIdentity, session.identity_id)
    user = db.get(UserAccount, identity.user_id) if identity else None
    if identity is None or user is None or not user.is_active or user.deleted_at:
        raise ApiError(401, ErrorCode.MINI_PROGRAM_REFRESH_INVALID)
    session.revoked_at = utcnow()
    pair = _new_pair(db, identity, user)
    db.commit()
    return user, identity, pair

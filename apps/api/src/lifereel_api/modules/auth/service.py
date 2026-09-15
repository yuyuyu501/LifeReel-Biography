from __future__ import annotations

from functools import lru_cache
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.models import utcnow
from lifereel_api.modules.auth import sms
from lifereel_api.modules.auth.models import (
    AccountAudit,
    AccountPhone,
    TenantMembership,
    UserAccount,
)
from lifereel_api.modules.auth.schemas import (
    AccountDelete,
    AccountPage,
    AccountRead,
    AdminCreate,
    AdminUpdate,
    AuthUserRead,
    LoginResponse,
    PasswordReset,
    RegisterRequest,
    SmsVerification,
)
from lifereel_api.modules.auth.security import create_token, hash_password, verify_password
from lifereel_api.modules.billing.service import lock_wallet
from lifereel_api.modules.identity.models import Tenant
from lifereel_api.modules.interview.models import Chapter


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    return hash_password("nonexistent-account-timing-padding")


def login(db: Session, email: str, password: str) -> tuple[LoginResponse, str]:
    user = db.scalar(
        select(UserAccount).where(
            or_(
                UserAccount.email == email.lower(),
                UserAccount.phone == email,
            )
        )
    )
    password_valid = verify_password(
        password, user.password_hash if user else _dummy_password_hash()
    )
    if user is None or not user.is_active or user.deleted_at or not password_valid:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, ErrorCode.AUTH_INVALID_CREDENTIALS)
    membership = db.scalar(select(TenantMembership).where(TenantMembership.user_id == user.id))
    if membership is None:
        raise ApiError(status.HTTP_403_FORBIDDEN, ErrorCode.AUTH_MEMBERSHIP_MISSING)
    auth_user = user_context(db, user.id, membership.tenant_id)
    token = create_token(
        {
            "sub": str(user.id),
            "tenant_id": str(membership.tenant_id),
            "role": membership.role,
            "version": user.session_version,
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
        phone=user.phone,
        display_name=user.display_name,
        tenant_id=tenant_id,
        role=membership.role,
        is_admin=user.is_admin,
    )


def register(db: Session, payload: RegisterRequest) -> AuthUserRead:
    if not get_settings().registration_enabled:
        raise ApiError(403, ErrorCode.REGISTRATION_DISABLED)
    sms.consume(db, payload, "register")
    return create_account(db, payload.display_name, payload.password, phone=payload.phone)


def create_account(
    db: Session,
    name: str,
    password: str,
    *,
    phone: str | None = None,
    email: str | None = None,
    actor_id: UUID | None = None,
) -> AuthUserRead:
    from lifereel_api.core.seed import DEFAULT_CHAPTERS

    try:
        tenant = Tenant(name=name, slug=f"family-{uuid4().hex}")
        user = UserAccount(
            email=email,
            phone=phone,
            display_name=name,
            password_hash=hash_password(password),
        )
        db.add_all([tenant, user])
        db.flush()
        if phone:
            claim_phone(db, user, phone)
        db.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role="owner"))
        for order, title, description, questions in DEFAULT_CHAPTERS:
            db.add(
                Chapter(
                    tenant_id=tenant.id,
                    order_index=order,
                    title=title,
                    description=description,
                    opening_questions=questions,
                    is_system=True,
                )
            )
        lock_wallet(db, tenant.id)
        audit(db, actor_id or user.id, user.id, "account.created")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, ErrorCode.AUTH_ACCOUNT_UNAVAILABLE) from exc
    return user_context(db, user.id, tenant.id)


def audit(db: Session, actor_id: UUID | None, user_id: UUID, action: str, **changes) -> None:
    db.add(AccountAudit(actor_id=actor_id, user_id=user_id, action=action, changes=changes))


def claim_phone(db: Session, user: UserAccount, phone: str) -> None:
    claim = db.get(AccountPhone, phone)
    if claim and claim.user_id != user.id:
        raise ApiError(409, ErrorCode.AUTH_ACCOUNT_UNAVAILABLE)
    if not claim:
        db.add(AccountPhone(phone=phone, user_id=user.id))


def require_user(db: Session, user_id: UUID | None, *, lock: bool = True) -> UserAccount:
    stmt = (
        select(UserAccount)
        .where(UserAccount.id == user_id, UserAccount.deleted_at.is_(None))
        .execution_options(populate_existing=True)
    )
    user = db.scalar(stmt.with_for_update() if lock else stmt)
    if user is None:
        raise ApiError(404, ErrorCode.AUTH_USER_NOT_FOUND)
    return user


def require_password(user: UserAccount, password: str) -> None:
    if not verify_password(password, user.password_hash):
        raise ApiError(400, ErrorCode.AUTH_PASSWORD_INCORRECT)


def reset_password(db: Session, payload: PasswordReset) -> None:
    sms.consume(db, payload, "reset_password")
    user = db.scalar(
        select(UserAccount).where(UserAccount.phone == payload.phone).with_for_update()
    )
    if user is None or user.deleted_at or not user.is_active:
        db.commit()
        raise ApiError(400, ErrorCode.AUTH_ACCOUNT_UNAVAILABLE)
    user.password_hash = hash_password(payload.password)
    user.session_version += 1
    audit(db, user.id, user.id, "password.reset")
    db.commit()


def list_accounts(db: Session, q: str, state: str, page: int, page_size: int) -> AccountPage:
    filters = [UserAccount.deleted_at.is_(None)]
    if state != "all":
        filters.append(UserAccount.is_active == (state == "active"))
    if q:
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filters.append(
            or_(
                *(
                    column.ilike(pattern, escape="\\")
                    for column in (UserAccount.display_name, UserAccount.email, UserAccount.phone)
                )
            )
        )
    total = db.scalar(select(func.count()).select_from(UserAccount).where(*filters)) or 0
    users = db.scalars(
        select(UserAccount)
        .where(*filters)
        .order_by(UserAccount.created_at.desc(), UserAccount.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return AccountPage(
        items=[AccountRead.model_validate(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
    )


def admin_create(db: Session, actor_id: UUID, payload: AdminCreate) -> AccountRead:
    result = create_account(
        db, payload.display_name, payload.password, email=payload.email, actor_id=actor_id
    )
    return AccountRead.model_validate(require_user(db, result.id))


def admin_update(db: Session, actor_id: UUID, user_id: UUID, payload: AdminUpdate) -> AccountRead:
    user = require_user(db, user_id)
    if user.is_admin:
        raise ApiError(403, ErrorCode.AUTH_ACCOUNT_PROTECTED)
    values = payload.model_dump(exclude_none=True)
    for key, value in values.items():
        if key == "password":
            user.password_hash = hash_password(value)
        else:
            setattr(user, key, value)
    if values:
        user.session_version += 1
        audit(db, actor_id, user.id, "account.updated", fields=list(values))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, ErrorCode.AUTH_ACCOUNT_UNAVAILABLE) from exc
    return AccountRead.model_validate(user)


def delete_account(
    db: Session, actor_id: UUID, user_id: UUID, payload: AccountDelete | None = None
) -> None:
    from lifereel_api.modules.billing.models import Wallet
    from lifereel_api.modules.jobs.models import Job

    user = require_user(db, user_id, lock=False)
    if payload:
        require_password(user, payload.current_password)
        if user.phone:
            if not payload.challenge_id or not payload.code:
                raise ApiError(400, ErrorCode.SMS_CODE_INVALID)
            sms.consume(
                db,
                SmsVerification(
                    phone=user.phone, challenge_id=payload.challenge_id, code=payload.code
                ),
                "delete_account",
            )
    user = require_user(db, user_id)
    if user.is_admin:
        raise ApiError(403, ErrorCode.AUTH_ACCOUNT_PROTECTED)
    if payload:
        require_password(user, payload.current_password)
    tenants = select(TenantMembership.tenant_id).where(TenantMembership.user_id == user.id)
    wallets = db.scalars(
        select(Wallet).where(Wallet.tenant_id.in_(tenants)).with_for_update()
    ).all()
    if any(w.paid_cents != 0 or w.frozen_paid_cents or w.frozen_bonus_cents for w in wallets):
        raise ApiError(409, ErrorCode.AUTH_ACCOUNT_HAS_OBLIGATIONS)
    if db.scalar(
        select(Job.id)
        .where(Job.tenant_id.in_(tenants), Job.status.in_(["queued", "running"]))
        .limit(1)
    ):
        raise ApiError(409, ErrorCode.AUTH_ACCOUNT_HAS_OBLIGATIONS)
    user.is_active = False
    user.deleted_at = utcnow()
    user.session_version += 1
    audit(db, actor_id, user.id, "account.deleted")
    db.commit()

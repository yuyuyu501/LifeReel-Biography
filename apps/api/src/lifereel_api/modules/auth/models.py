from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from lifereel_api.core.database import Base
from lifereel_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class UserAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_accounts"

    __table_args__ = (UniqueConstraint("email"),)

    email: Mapped[str | None] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    session_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountPhone(TimestampMixin, Base):
    __tablename__ = "account_phones"

    phone: Mapped[str] = mapped_column(String(20), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("user_accounts.id"), index=True)


class SmsChallenge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sms_challenges"

    phone: Mapped[str] = mapped_column(String(20), index=True)
    purpose: Mapped[str] = mapped_column(String(24))
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    resets_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AccountAudit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "account_audits"

    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    user_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    action: Mapped[str] = mapped_column(String(40))
    changes: Mapped[dict] = mapped_column(JSON, default=dict)


class TenantMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_membership_tenant_user"),)

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("user_accounts.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(32), default="owner")

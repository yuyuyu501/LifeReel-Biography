from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from lifereel_api.core.database import Base
from lifereel_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class Wallet(TimestampMixin, Base):
    __tablename__ = "wallets"
    __table_args__ = (
        CheckConstraint("bonus_cents >= 0", name="nonnegative_balance"),
        CheckConstraint(
            "frozen_paid_cents >= 0 AND frozen_bonus_cents >= 0", name="nonnegative_frozen"
        ),
        CheckConstraint(
            "bonus_cents >= frozen_bonus_cents",
            name="covered_frozen",
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), primary_key=True)
    paid_cents: Mapped[int] = mapped_column(Integer, default=0)
    bonus_cents: Mapped[int] = mapped_column(Integer, default=0)
    frozen_paid_cents: Mapped[int] = mapped_column(Integer, default=0)
    frozen_bonus_cents: Mapped[int] = mapped_column(Integer, default=0)
    token_remainder_nano: Mapped[int] = mapped_column(BigInteger, default=0)


class Charge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "billing_charges"
    __table_args__ = (
        UniqueConstraint("tenant_id", "business_key"),
        CheckConstraint(
            "amount_cents >= 0 AND paid_cents >= 0 AND bonus_cents >= 0", name="positive_charge"
        ),
        CheckConstraint("amount_cents = paid_cents + bonus_cents", name="charge_split"),
        CheckConstraint("status IN ('reserved', 'settled', 'released')", name="valid_status"),
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("wallets.tenant_id"), index=True)
    business_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(300))
    amount_cents: Mapped[int] = mapped_column(Integer)
    paid_cents: Mapped[int] = mapped_column(Integer)
    bonus_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="reserved")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    price_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class LedgerEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wallet_ledger"
    __table_args__ = (UniqueConstraint("tenant_id", "event_key"),)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("wallets.tenant_id"), index=True)
    charge_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("billing_charges.id"))
    event_key: Mapped[str] = mapped_column(String(240))
    event: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(300))
    amount_cents: Mapped[int] = mapped_column(Integer)
    paid_delta: Mapped[int] = mapped_column(Integer, default=0)
    bonus_delta: Mapped[int] = mapped_column(Integer, default=0)
    frozen_delta: Mapped[int] = mapped_column(Integer, default=0)
    available_after_cents: Mapped[int] = mapped_column(Integer)


class UsageEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_usage"
    __table_args__ = (UniqueConstraint("tenant_id", "operation", "provider_request_id", "status"),)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    operation: Mapped[str] = mapped_column(String(48))
    reference: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(20))
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer)
    provider_request_id: Mapped[str | None] = mapped_column(String(200))
    error_code: Mapped[str | None] = mapped_column(String(80))
    metering: Mapped[dict] = mapped_column(JSON, default=dict)


class RechargeOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recharge_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_id"),
        UniqueConstraint("verified_reference"),
        CheckConstraint("amount_cents BETWEEN 1 AND 20000", name="recharge_amount"),
        CheckConstraint(
            "status IN ('pending', 'submitted', 'credited', 'rejected', 'cancelled')",
            name="recharge_status",
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("wallets.tenant_id"), index=True)
    request_id: Mapped[UUID] = mapped_column(Uuid)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    payer_reference: Mapped[str | None] = mapped_column(String(64))
    verified_reference: Mapped[str | None] = mapped_column(String(64))
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    review_note: Mapped[str | None] = mapped_column(String(300))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

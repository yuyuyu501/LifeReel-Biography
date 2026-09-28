from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from lifereel_api.core.database import Base
from lifereel_api.core.models import UUIDPrimaryKeyMixin


class OutboxEvent(UUIDPrimaryKeyMixin, Base):
    """Durable event record written with the job transaction."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_events_dispatch", "status", "occurred_at"),
        Index("ix_outbox_events_tenant", "tenant_id", "occurred_at"),
    )
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(120))
    schema_version: Mapped[int] = mapped_column(default=1)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid)
    idempotency_key: Mapped[str | None] = mapped_column(String(180), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

"""Durable invocation results; prompts and raw voice utterances are not stored."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from lifereel_api.core.database import Base
from lifereel_api.core.models import UUIDPrimaryKeyMixin


class ModelInvocation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "model_invocations"
    __table_args__ = {"schema": "model_gateway"}
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.tenants.id", ondelete="CASCADE")
    )
    operation: Mapped[str] = mapped_column(String(120))
    request_digest: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24))
    response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

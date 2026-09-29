from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from lifereel_api.core.database import Base
from lifereel_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class Publication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "publications"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    production_run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("production_runs.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    audience: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="published")
    access_token: Mapped[str] = mapped_column(String(64), unique=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

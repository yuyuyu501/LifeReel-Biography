from __future__ import annotations

from uuid import UUID

from sqlalchemy import JSON, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from lifereel_api.core.database import Base
from lifereel_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class ChapterReferencePackage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chapter_reference_packages"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    production_run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("production_runs.id", ondelete="CASCADE"), unique=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    chapter_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), default="ready")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

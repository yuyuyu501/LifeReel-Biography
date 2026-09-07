from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lifereel_api.core.database import Base
from lifereel_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class Tenant(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Person(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "persons"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str] = mapped_column(String(120))
    preferred_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    birthplace: Mapped[str | None] = mapped_column(String(240), nullable=True)
    relation_to_owner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_subject: Mapped[bool] = mapped_column(Boolean, default=True)
    biography_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_minor: Mapped[bool] = mapped_column(Boolean, default=False)
    guardian_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    interview_sessions = relationship(
        "InterviewSession", back_populates="subject", cascade="all, delete-orphan"
    )

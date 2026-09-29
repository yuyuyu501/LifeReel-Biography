from __future__ import annotations

from uuid import UUID

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from lifereel_api.core.database import Base
from lifereel_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class MemoryClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memory_claims"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_round_id", name="uq_claim_tenant_source_round"),
        UniqueConstraint(
            "tenant_id",
            "source_observation_id",
            name="uq_claim_tenant_source_observation",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    interview_session_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True, nullable=True
    )
    source_round_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("interview_rounds.id", ondelete="CASCADE"), nullable=True
    )
    source_observation_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("evidence_observations.id", ondelete="CASCADE"), nullable=True
    )
    chapter_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True
    )
    claim_text: Mapped[str] = mapped_column(Text)
    source_quote: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(48), default="recollection")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    review_status: Mapped[str] = mapped_column(String(32), default="unreviewed")
    extraction_provider: Mapped[str] = mapped_column(String(80), default="rule")
    extraction_model: Mapped[str | None] = mapped_column(String(180), nullable=True)


class MemoryEntity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memory_entities"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "subject_id",
            "entity_type",
            "normalized_name",
            name="uq_memory_entity",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    entity_type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(180))
    normalized_name: Mapped[str] = mapped_column(String(180))
    relationship: Mapped[str] = mapped_column(String(120), default="相关人物")
    source_claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list)


class TimelineAnchor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "timeline_anchors"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("memory_claims.id", ondelete="CASCADE"), index=True
    )
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_text: Mapped[str] = mapped_column(String(120))
    event_text: Mapped[str] = mapped_column(Text)
    precision: Mapped[str] = mapped_column(String(24), default="approximate")


class MemoryConflict(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memory_conflicts"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    conflict_key: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open")

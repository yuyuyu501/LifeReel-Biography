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
        {"schema": "memory"},
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.persons.id", ondelete="CASCADE"), index=True
    )
    interview_session_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("interview.interview_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    source_round_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("interview.interview_rounds.id", ondelete="CASCADE"), nullable=True
    )
    source_observation_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("media.evidence_observations.id", ondelete="CASCADE"), nullable=True
    )
    chapter_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("interview.chapters.id", ondelete="SET NULL"), nullable=True
    )
    profile_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("interview.life_profile_entries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    claim_text: Mapped[str] = mapped_column(Text)
    source_quote: Mapped[str] = mapped_column(Text)
    source_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    fact_overrides: Mapped[list[dict]] = mapped_column(JSON, default=list, server_default="[]")
    claim_type: Mapped[str] = mapped_column(String(48), default="recollection")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    review_status: Mapped[str] = mapped_column(String(32), default="unreviewed")
    extraction_provider: Mapped[str] = mapped_column(String(80), default="rule")
    extraction_model: Mapped[str | None] = mapped_column(String(180), nullable=True)

    @property
    def current_text(self):
        text = self.claim_text
        for correction in self.fact_overrides or []:
            if correction["target_revision"] == self.source_revision:
                text = text.replace(correction["old_text"], correction["new_text"], 1)
        return text

    @classmethod
    def current_source(cls):
        """A queued/failed correction must not expose facts extracted from an older answer."""
        from sqlalchemy import and_, or_, select

        from lifereel_api.modules.interview.models import InterviewRound
        from lifereel_api.modules.interview.profile_models import LifeProfileEntry

        return and_(
            or_(
                cls.source_round_id.is_(None),
                select(InterviewRound.id)
                .where(
                    InterviewRound.id == cls.source_round_id,
                    InterviewRound.tenant_id == cls.tenant_id,
                    InterviewRound.answer_version == cls.source_revision,
                )
                .exists(),
            ),
            or_(
                cls.profile_entry_id.is_(None),
                select(LifeProfileEntry.id)
                .where(
                    LifeProfileEntry.id == cls.profile_entry_id,
                    LifeProfileEntry.tenant_id == cls.tenant_id,
                    LifeProfileEntry.version_number == cls.source_revision,
                    LifeProfileEntry.state == "filled",
                    LifeProfileEntry.certainty.not_in(["pending", "disputed"]),
                    LifeProfileEntry.use_scope.in_(["works", "pseudonym"]),
                )
                .exists(),
            ),
        )


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
        {"schema": "memory"},
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.persons.id", ondelete="CASCADE"), index=True
    )
    entity_type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(180))
    normalized_name: Mapped[str] = mapped_column(String(180))
    relationship: Mapped[str] = mapped_column(String(120), default="相关人物")
    source_claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list)


class TimelineAnchor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "timeline_anchors"
    __table_args__ = {"schema": "memory"}

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.persons.id", ondelete="CASCADE"), index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("memory.memory_claims.id", ondelete="CASCADE"), index=True
    )
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_text: Mapped[str] = mapped_column(String(120))
    event_text: Mapped[str] = mapped_column(Text)
    precision: Mapped[str] = mapped_column(String(24), default="approximate")


class MemoryConflict(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memory_conflicts"
    __table_args__ = {"schema": "memory"}

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.persons.id", ondelete="CASCADE"), index=True
    )
    claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    conflict_key: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open")

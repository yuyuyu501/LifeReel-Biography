from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from lifereel_api.core.database import Base
from lifereel_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class SourceAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_assets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "subject_id", "sha256", name="uq_asset_tenant_subject_sha256"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    interview_session_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("interview_sessions.id", ondelete="SET NULL"), nullable=True
    )
    chapter_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="ready")
    consent_scope: Mapped[str] = mapped_column(String(32), default="private")
    consent_status: Mapped[str] = mapped_column(String(24), default="unknown")
    age_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    identity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    voice_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_status: Mapped[str] = mapped_column(String(24), default="pending")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    derived_from_asset_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("source_assets.id", ondelete="SET NULL"), nullable=True
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def is_redraw(self) -> bool:
        return (self.metadata_json or {}).get("purpose") == "photo_redraw"

    @property
    def is_restoration(self) -> bool:
        return (self.metadata_json or {}).get("purpose") == "photo_restoration"


class EvidenceUpload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence_uploads"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id", ondelete="CASCADE"))
    interview_session_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("interview_sessions.id", ondelete="SET NULL"), nullable=True
    )
    chapter_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    consent_scope: Mapped[str] = mapped_column(String(32))
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    asset_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("source_assets.id", ondelete="SET NULL"), nullable=True
    )


class Transcript(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "transcripts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_asset_id", name="uq_transcript_tenant_asset"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("source_assets.id", ondelete="CASCADE"), index=True
    )
    language: Mapped[str] = mapped_column(String(24), default="zh-CN")
    status: Mapped[str] = mapped_column(String(32), default="ready")
    current_version: Mapped[int] = mapped_column(Integer, default=1)


class TranscriptVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "transcript_versions"
    __table_args__ = (
        UniqueConstraint("transcript_id", "version_number", name="uq_transcript_version"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    transcript_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("transcripts.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    edit_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TranscriptSegment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "transcript_segments"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    transcript_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("transcript_versions.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speaker_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    text: Mapped[str] = mapped_column(Text)


class EvidenceObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence_observations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_asset_id",
            "version_number",
            name="uq_evidence_observation_version",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("source_assets.id", ondelete="CASCADE"), index=True
    )
    source_transcript_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("transcript_versions.id", ondelete="SET NULL"), nullable=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    analysis_kind: Mapped[str] = mapped_column(String(48))
    text: Mapped[str] = mapped_column(Text)
    locator: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    review_status: Mapped[str] = mapped_column(String(32), default="unreviewed")
    provider: Mapped[str] = mapped_column(String(80), default="local")
    model_name: Mapped[str | None] = mapped_column(String(180), nullable=True)

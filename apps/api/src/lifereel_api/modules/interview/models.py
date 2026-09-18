from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lifereel_api.core.database import Base
from lifereel_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class Chapter(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("tenant_id", "order_index", name="uq_chapter_tenant_order"),)

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    age_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    age_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    opening_questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InterviewSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "subject_id",
            "chapter_id",
            name="uq_interview_subject_chapter",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id", ondelete="CASCADE"))
    chapter_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True
    )
    topic_hint: Mapped[str | None] = mapped_column(String(240), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    round_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    subject = relationship("Person", back_populates="interview_sessions")
    chapter = relationship("Chapter")
    rounds = relationship(
        "InterviewRound",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="InterviewRound.round_index",
    )


class InterviewRound(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "interview_rounds"
    __table_args__ = (UniqueConstraint("session_id", "round_index", name="uq_round_session_index"),)

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("interview_sessions.id", ondelete="CASCADE")
    )
    round_index: Mapped[int] = mapped_column(Integer)
    question_text: Mapped[str] = mapped_column(Text)
    question_intent: Mapped[str | None] = mapped_column(String(80), nullable=True)
    question_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_asset_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    transcript_status: Mapped[str] = mapped_column(String(32), default="not_required")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session = relationship("InterviewSession", back_populates="rounds")


class InterviewTurnWorkflow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "interview_turn_workflows"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_interview_turn_tenant_idempotency",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True
    )
    round_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("interview_rounds.id", ondelete="CASCADE"), index=True
    )
    chapter_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    script_scene_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    script_project_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    next_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_question_intent: Mapped[str | None] = mapped_column(String(80), nullable=True)
    missing_topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    script_brief: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def retry_allowed(self) -> bool:
        from lifereel_api.modules.memory.recovery import allowed

        return allowed(self)

    @property
    def retry_after_seconds(self) -> int:
        from lifereel_api.modules.memory.recovery import retry_after

        return retry_after(self) if self.status == "failed" else 0


class InterviewVoiceCall(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "interview_voice_calls"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default="connecting", index=True)
    messages: Mapped[list[dict]] = mapped_column(JSON, default=list)
    usage: Mapped[list[dict]] = mapped_column(JSON, default=list)
    last_round_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    source_asset_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    workflow_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

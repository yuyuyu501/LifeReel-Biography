from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from lifereel_api.core.database import Base
from lifereel_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class ScriptGenerationReceipt(Base):
    __tablename__ = "script_generation_receipts"
    __table_args__ = {"schema": "script"}
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("identity.tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    request_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("script.script_projects.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default="completed", server_default="completed")
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class ScriptProject(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "script_projects"
    __table_args__ = (
        Index(
            "uq_script_project_active_subject",
            "tenant_id",
            "subject_id",
            unique=True,
            postgresql_where=text("status <> 'superseded'"),
            sqlite_where=text("status <> 'superseded'"),
        ),
        {"schema": "script"},
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.persons.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(180))
    mode: Mapped[str] = mapped_column(String(32), default="single_chapter")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    audience: Mapped[str] = mapped_column(String(32), default="family")
    source_claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String(32), default="needs_review")
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generation_provider: Mapped[str] = mapped_column(String(80), default="rule")
    generation_model: Mapped[str | None] = mapped_column(String(180), nullable=True)
    source_type: Mapped[str] = mapped_column(String(24), default="legacy", server_default="legacy")
    source_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class ScriptScene(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "script_scenes"
    __table_args__ = (
        UniqueConstraint("project_id", "chapter_id", name="uq_script_scene_project_chapter"),
        {"schema": "script"},
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.tenants.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("script.script_projects.id", ondelete="CASCADE"), index=True
    )
    chapter_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("interview.chapters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(180))
    plot: Mapped[str | None] = mapped_column(Text, nullable=True)
    dialogues: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    narration: Mapped[str] = mapped_column(Text)
    visual_prompt: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=12)
    source_claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    visual_constraints: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    story_skeleton: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), default="needs_review")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # None selects existing chapter media; [] is an intentionally empty selection.
    reference_asset_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class ScriptShot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "script_shots"
    __table_args__ = {"schema": "script"}

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.tenants.id", ondelete="CASCADE"), index=True
    )
    scene_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("script.script_scenes.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer)
    shot_type: Mapped[str] = mapped_column(String(48), default="medium")
    visual_prompt: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=6)
    source_claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    visual_constraints: Mapped[dict | None] = mapped_column(JSON, nullable=True)

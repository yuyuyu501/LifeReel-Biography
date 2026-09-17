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
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("persons.id", ondelete="CASCADE"), index=True
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


class ScriptScene(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "script_scenes"
    __table_args__ = (
        UniqueConstraint("project_id", "chapter_id", name="uq_script_scene_project_chapter"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("script_projects.id", ondelete="CASCADE"), index=True
    )
    chapter_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(180))
    plot: Mapped[str | None] = mapped_column(Text, nullable=True)
    dialogues: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    narration: Mapped[str] = mapped_column(Text)
    visual_prompt: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=12)
    source_claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String(32), default="needs_review")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # None selects existing chapter media; [] is an intentionally empty selection.
    reference_asset_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class ScriptShot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "script_shots"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    scene_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("script_scenes.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer)
    shot_type: Mapped[str] = mapped_column(String(48), default="medium")
    visual_prompt: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=6)
    source_claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list)

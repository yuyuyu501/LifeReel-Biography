from __future__ import annotations

from uuid import UUID

from sqlalchemy import JSON, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from lifereel_api.core.database import Base
from lifereel_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class ProductionRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "production_runs"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("script_projects.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="queued")
    provider: Mapped[str] = mapped_column(String(64), default="mock")
    audience: Mapped[str] = mapped_column(String(32), default="family")
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost: Mapped[float] = mapped_column(Float, default=0.0)
    output_manifest: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class GeneratedAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "generated_assets"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    production_run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("production_runs.id", ondelete="CASCADE"), index=True
    )
    scene_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("script_scenes.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(120))
    storage_key: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64))
    generation_parameters: Mapped[dict] = mapped_column(JSON, default=dict)

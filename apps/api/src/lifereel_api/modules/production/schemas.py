from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProductionStart(BaseModel):
    project_id: UUID
    audience: str = Field(default="family", pattern="^(private|family|friends|public)$")
    provider: str | None = Field(default=None, max_length=64)


class GeneratedAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    scene_id: UUID | None
    kind: str
    provider: str
    mime_type: str
    sha256: str
    generation_parameters: dict


class ProductionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    job_id: UUID | None
    status: str
    provider: str
    audience: str
    estimated_cost: float
    actual_cost: float
    output_manifest: dict | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    assets: list[GeneratedAssetRead] = Field(default_factory=list)

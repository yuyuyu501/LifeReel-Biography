from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PublicationCreate(BaseModel):
    production_run_id: UUID
    audience: str = Field(pattern="^(private|family|friends|public)$")


class PublicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    production_run_id: UUID
    subject_id: UUID
    audience: str
    status: str
    access_token: str
    published_at: datetime
    withdrawn_at: datetime | None
    created_at: datetime


class PublicPublicationRead(BaseModel):
    id: UUID
    audience: str
    status: str
    published_at: datetime
    production_run_id: UUID

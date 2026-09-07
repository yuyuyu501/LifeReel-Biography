from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConsentCreate(BaseModel):
    subject_id: UUID
    consent_type: str = Field(
        pattern="^(interview|portrait|voice|production|publication|guardian)$"
    )
    scope: str = Field(pattern="^(private|family|friends|public)$")
    granted_by: str = Field(min_length=1, max_length=180)
    evidence_note: str | None = None
    expires_at: datetime | None = None


class ConsentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    subject_id: UUID
    consent_type: str
    scope: str
    status: str
    granted_by: str
    evidence_note: str | None
    expires_at: datetime | None
    created_at: datetime


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    actor: str
    action: str
    resource_type: str
    resource_id: str
    details: dict
    created_at: datetime

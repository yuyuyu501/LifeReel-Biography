from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobFailure(BaseModel):
    error_code: str = Field(default="WORKER_ERROR", pattern="^[A-Z][A-Z0-9_]+$", max_length=120)
    error_message: str | None = Field(default=None, max_length=4000)


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    status: str
    idempotency_key: str | None
    payload: dict
    result: dict | None
    error_code: str | None
    error_message: str | None
    attempt_count: int
    created_at: datetime
    updated_at: datetime

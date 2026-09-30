from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class EventEnvelope(BaseModel):
    """Versioned event contract for the transactional outbox and future bus."""

    model_config = ConfigDict(extra="forbid")
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9]+(?:\.[a-z0-9_-]+)+$")
    schema_version: int = Field(default=1, ge=1)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_service: str = Field(default="api", min_length=2, max_length=64)
    tenant_id: UUID
    aggregate_id: UUID
    correlation_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, max_length=180)
    payload: dict[str, Any] = Field(default_factory=dict)


def event_type_for_job(kind: str) -> str:
    return {
        "interview.turn.process": "interview.turn.queued",
        "book.chapter.generate": "book.chapter.queued",
        "production.render": "media.production.queued",
        "production.cleanup": "media.cleanup.queued",
        "evidence.photo_redraw": "media.photo_redraw.queued",
        "photo.restoration": "media.photo_restoration.queued",
    }.get(kind, "worker.job.queued")

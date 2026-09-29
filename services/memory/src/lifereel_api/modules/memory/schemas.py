from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MemoryCompileRequest(BaseModel):
    interview_session_id: UUID | None = None
    subject_id: UUID | None = None


class MemoryClaimRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_id: UUID
    interview_session_id: UUID | None
    source_round_id: UUID | None
    source_observation_id: UUID | None
    chapter_id: UUID | None
    claim_text: str
    source_quote: str
    claim_type: str
    confidence: float
    review_status: str
    extraction_provider: str
    extraction_model: str | None
    created_at: datetime
    updated_at: datetime


class MemoryReviewRequest(BaseModel):
    status: str


class MemoryEntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    subject_id: UUID
    entity_type: str
    name: str
    relationship: str
    source_claim_ids: list[str]


class TimelineAnchorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    subject_id: UUID
    claim_id: UUID
    year: int | None
    time_text: str
    event_text: str
    precision: str


class MemoryConflictRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    subject_id: UUID
    claim_ids: list[str]
    conflict_key: str
    description: str
    status: str


class MemoryOverview(BaseModel):
    claim_count: int
    reviewed_count: int
    entity_count: int
    timeline_count: int
    open_conflict_count: int
    covered_chapter_ids: list[UUID]
    coverage_ratio: float


class MemoryGraphNode(BaseModel):
    id: str
    kind: str
    label: str
    description: str | None = None
    time_text: str | None = None
    source_claim_ids: list[str]


class MemoryGraphEdge(BaseModel):
    id: str
    source_id: str
    target_id: str
    relationship: str
    source_claim_ids: list[str]


class MemoryGraphRead(BaseModel):
    subject_id: UUID
    nodes: list[MemoryGraphNode]
    edges: list[MemoryGraphEdge]


class MemoryCompileResult(BaseModel):
    created_count: int
    existing_count: int
    claims: list[MemoryClaimRead]

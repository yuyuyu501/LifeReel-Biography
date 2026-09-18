from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SourceAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_id: UUID
    interview_session_id: UUID | None
    chapter_id: UUID | None = None
    kind: str
    original_filename: str
    mime_type: str
    byte_size: int
    sha256: str
    status: str
    consent_scope: str
    consent_status: str = "unknown"
    age_start: int | None = None
    age_end: int | None = None
    quality_score: float | None = None
    identity_score: float | None = None
    voice_score: float | None = None
    analysis_status: str = "pending"
    derived_from_asset_id: UUID | None = None
    is_redraw: bool = False
    is_restoration: bool = False
    captured_at: datetime
    created_at: datetime


class DirectUploadCreate(BaseModel):
    subject_id: UUID
    interview_session_id: UUID | None = None
    kind: str = Field(pattern="^(audio|photo|video|document)$")
    original_filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(max_length=120)
    byte_size: int = Field(gt=0)
    consent_scope: str = Field(default="private", pattern="^(private|family|friends|public)$")


class DirectUploadRead(BaseModel):
    upload_id: UUID
    url: str
    fields: dict[str, str]
    expires_at: datetime


class DirectUploadComplete(BaseModel):
    upload_id: UUID


class TranscriptCreate(BaseModel):
    text: str = Field(min_length=1)
    language: str = Field(default="zh-CN", max_length=24)
    source: str = Field(default="manual", pattern="^(manual|mock_asr|provider_asr)$")


class TranscriptRevisionCreate(BaseModel):
    text: str = Field(min_length=1)
    edit_reason: str = Field(min_length=1, max_length=240)


class TranscriptSegmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_index: int
    start_ms: int | None
    end_ms: int | None
    speaker_label: str | None
    text: str


class TranscriptVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version_number: int
    text: str
    source: str
    edit_reason: str | None
    created_at: datetime
    segments: list[TranscriptSegmentRead] = Field(default_factory=list)


class TranscriptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_asset_id: UUID
    language: str
    status: str
    current_version: int
    created_at: datetime
    updated_at: datetime
    versions: list[TranscriptVersionRead] = Field(default_factory=list)


class EvidenceObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_id: UUID
    source_asset_id: UUID
    source_transcript_version_id: UUID | None
    version_number: int
    analysis_kind: str
    text: str
    locator: dict
    confidence: float
    review_status: str
    provider: str
    model_name: str | None
    created_at: datetime

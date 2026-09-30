from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BookCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    subject_id: UUID
    title: str | None = Field(default=None, min_length=1, max_length=180)


class BookGenerate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID
    chapter_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=40)
    overwrite: bool = False
    expected_versions: dict[str, int] = Field(default_factory=dict)


class ChapterEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=1, strict=True)
    title: str = Field(min_length=1, max_length=180)
    body: str = Field(min_length=1, max_length=12000)


class RevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version_number: int
    title: str
    body: str
    word_count: int
    source_claim_ids: list[str]
    author: str
    generation_model: str | None
    created_at: datetime


class ChapterRead(BaseModel):
    id: UUID
    chapter_id: UUID
    title: str
    order_index: int
    version_number: int
    status: str
    source_count: int
    stale: bool
    job_id: UUID | None
    error_code: str | None
    current: RevisionRead | None


class BookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    subject_id: UUID
    title: str
    target_words: int
    chapters: list[ChapterRead]


class GenerationRead(BaseModel):
    job_ids: list[UUID]
    skipped_chapter_ids: list[UUID]

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScriptDialogue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["narration", "dialogue"]
    speaker: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=2000)


class ScriptGenerateRequest(BaseModel):
    subject_id: UUID
    title: str | None = Field(default=None, max_length=180)
    mode: str = Field(default="single_chapter", pattern="^(single_chapter|multi_chapter)$")
    audience: str = Field(default="family", pattern="^(private|family|friends|public)$")
    chapter_id: UUID | None = None
    idempotency_key: UUID | None = None


class ScriptSceneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chapter_id: UUID | None
    order_index: int
    heading: str
    plot: str | None = None
    dialogues: list[ScriptDialogue] | None = None
    narration: str
    visual_prompt: str
    duration_seconds: int
    source_claim_ids: list[str]


class ScriptShotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scene_id: UUID
    order_index: int
    shot_type: str
    visual_prompt: str
    duration_seconds: int
    source_claim_ids: list[str]


class ScriptProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_id: UUID
    title: str
    mode: str
    status: str
    audience: str
    source_claim_ids: list[str]
    version_number: int
    generation_provider: str
    generation_model: str | None
    created_at: datetime
    updated_at: datetime
    scenes: list[ScriptSceneRead] = Field(default_factory=list)
    shots: list[ScriptShotRead] = Field(default_factory=list)

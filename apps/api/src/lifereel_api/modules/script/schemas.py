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


class VisualConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    face_policy: Literal["unspecified", "no_identifiable_faces", "faces_allowed"] = "unspecified"
    required_elements: list[str] = Field(default_factory=list, max_length=16)
    forbidden_elements: list[str] = Field(default_factory=list, max_length=16)
    notes: str | None = Field(default=None, max_length=500)


class StorySkeleton(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opening: str = Field(min_length=1, max_length=600)
    beats: list[str] = Field(min_length=1, max_length=6)
    turning_point: str | None = Field(default=None, max_length=600)
    ending: str = Field(min_length=1, max_length=600)


class ScriptGenerateRequest(BaseModel):
    subject_id: UUID
    title: str | None = Field(default=None, max_length=180)
    mode: str = Field(default="single_chapter", pattern="^(single_chapter|multi_chapter)$")
    audience: str = Field(default="family", pattern="^(private|family|friends|public)$")
    chapter_id: UUID | None = None
    idempotency_key: UUID | None = None


class ScriptShotUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    shot_type: Literal["wide", "medium", "closeup", "detail", "archive"]
    visual_prompt: str = Field(min_length=1, max_length=4000)
    duration_seconds: int = Field(ge=1, le=300, strict=True)
    visual_constraints: VisualConstraints = Field(default_factory=VisualConstraints)


class ScriptSceneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=1)
    heading: str = Field(min_length=1, max_length=180)
    plot: str | None = Field(default=None, max_length=4000)
    dialogues: list[ScriptDialogue] = Field(min_length=1, max_length=40)
    visual_prompt: str = Field(min_length=1, max_length=4000)
    duration_seconds: int = Field(ge=4, le=300, strict=True)
    visual_constraints: VisualConstraints = Field(default_factory=VisualConstraints)
    story_skeleton: StorySkeleton | None = None
    shots: list[ScriptShotUpdate] = Field(max_length=40)


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
    reference_asset_ids: list[UUID] | None = None
    visual_constraints: VisualConstraints | None = None
    story_skeleton: StorySkeleton | None = None


class ScriptReferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    asset_ids: list[UUID] = Field(max_length=12)


class ScriptShotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scene_id: UUID
    order_index: int
    shot_type: str
    visual_prompt: str
    duration_seconds: int
    source_claim_ids: list[str]
    visual_constraints: VisualConstraints | None = None


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

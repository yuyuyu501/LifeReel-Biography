from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class SourcedNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1000)
    source_revision_ids: list[UUID] = Field(min_length=1, max_length=40)


class AdaptationBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: str = Field(min_length=1, max_length=1000)
    intended_audience: Literal["private", "family", "friends", "public"]
    dramatic_question: str | None = Field(default=None, max_length=1000)
    time_scope: str | None = Field(default=None, max_length=500)
    must_include: list[SourcedNote] = Field(default_factory=list, max_length=40)
    must_avoid: list[str] = Field(default_factory=list, max_length=40)
    tone: str | None = Field(default=None, max_length=500)
    source_revision_ids: list[UUID] = Field(min_length=1, max_length=40)


class StoryBibleEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=180)
    notes: list[SourcedNote] = Field(default_factory=list, max_length=20)
    source_revision_ids: list[UUID] = Field(min_length=1, max_length=40)


class StoryTimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    event: str = Field(min_length=1, max_length=500)
    time_expression: str | None = Field(default=None, max_length=180)
    character_refs: list[str] = Field(default_factory=list, max_length=20)
    location_ref: str | None = Field(default=None, max_length=64)
    source_revision_ids: list[UUID] = Field(min_length=1, max_length=40)


class StoryBible(BaseModel):
    model_config = ConfigDict(extra="forbid")

    characters: list[StoryBibleEntry] = Field(default_factory=list, max_length=80)
    locations: list[StoryBibleEntry] = Field(default_factory=list, max_length=80)
    timeline: list[StoryTimelineEntry] = Field(default_factory=list, max_length=120)
    key_objects: list[StoryBibleEntry] = Field(default_factory=list, max_length=80)
    constraints: list[str] = Field(default_factory=list, max_length=40)
    source_revision_ids: list[UUID] = Field(default_factory=list, max_length=40)


class SequencePlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    order_index: int = Field(ge=1, strict=True)
    title: str = Field(min_length=1, max_length=180)
    narrative_role: Literal[
        "opening", "setup", "development", "turning_point", "aftermath", "closing",
        "transition", "montage",
    ]
    summary: str = Field(min_length=1, max_length=2000)
    source_revision_ids: list[UUID] = Field(min_length=1, max_length=40)
    character_refs: list[str] = Field(default_factory=list, max_length=20)
    location_refs: list[str] = Field(default_factory=list, max_length=20)


class SequencePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SequencePlanItem] = Field(min_length=1, max_length=120)


class AdaptationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adaptation_brief: AdaptationBrief
    story_bible: StoryBible
    sequence_plan: SequencePlan


class ScriptAdaptationPlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    adaptation_brief: AdaptationBrief
    story_bible: StoryBible
    sequence_plan: SequencePlan


class ScriptGenerateRequest(BaseModel):
    subject_id: UUID
    title: str | None = Field(default=None, max_length=180)
    mode: str = Field(default="single_chapter", pattern="^(single_chapter|multi_chapter)$")
    audience: str = Field(default="family", pattern="^(private|family|friends|public)$")
    chapter_id: UUID | None = None
    idempotency_key: UUID | None = None
    book_id: UUID | None = None
    book_revision_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=40)
    # Retained for old request fingerprints; whole-book adaptation ignores this hint.
    duration_seconds: int | None = Field(default=45, ge=1, strict=True)
    adaptation_instructions: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def exclusive_book_sources(self):
        if self.book_id and self.book_revision_ids:
            raise ValueError("book_id and book_revision_ids cannot be combined")
        return self


class ScriptShotUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    shot_type: Literal["wide", "medium", "closeup", "detail", "archive"]
    visual_prompt: str = Field(min_length=1, max_length=4000)
    duration_seconds: int = Field(ge=1, strict=True)
    visual_constraints: VisualConstraints = Field(default_factory=VisualConstraints)


class ScriptSceneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=1)
    heading: str = Field(min_length=1, max_length=180)
    plot: str | None = Field(default=None, max_length=4000)
    dialogues: list[ScriptDialogue] = Field(min_length=1, max_length=40)
    visual_prompt: str = Field(min_length=1, max_length=4000)
    duration_seconds: int = Field(ge=4, strict=True)
    visual_constraints: VisualConstraints = Field(default_factory=VisualConstraints)
    story_skeleton: StorySkeleton | None = None
    shots: list[ScriptShotUpdate]


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
    adaptation_metadata: dict = Field(default_factory=dict)


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
    adaptation_metadata: dict = Field(default_factory=dict)


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
    source_type: str = "legacy"
    source_snapshot: dict = Field(default_factory=dict)
    adaptation_brief: AdaptationBrief | None = None
    story_bible: StoryBible | None = None
    sequence_plan: SequencePlan | None = None
    source_stale: bool = False

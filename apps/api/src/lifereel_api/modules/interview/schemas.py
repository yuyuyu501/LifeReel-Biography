from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lifereel_api.modules.evidence.schemas import SourceAssetRead
from lifereel_api.modules.script.schemas import ScriptProjectRead


class ChapterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_index: int
    title: str
    description: str | None
    opening_questions: list[str]
    is_system: bool


class InterviewStart(BaseModel):
    subject_id: UUID
    chapter_id: UUID | None = None
    topic_hint: str | None = Field(default=None, max_length=240)


class InterviewRoundCreate(BaseModel):
    question_text: str = Field(min_length=1)
    question_intent: str | None = Field(default=None, max_length=80)
    question_source: str | None = Field(default=None, max_length=80)


class InterviewAnswer(BaseModel):
    answer_text: str = Field(min_length=1)
    source_asset_id: UUID | None = None


class InterviewRoundRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    round_index: int
    question_text: str
    question_intent: str | None
    question_source: str | None
    answer_text: str | None
    source_asset_id: UUID | None
    transcript_status: str
    created_at: datetime
    answered_at: datetime | None


class InterviewSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_id: UUID
    chapter_id: UUID | None
    topic_hint: str | None
    status: str
    round_count: int
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    rounds: list[InterviewRoundRead] = Field(default_factory=list)


class NextQuestionRead(BaseModel):
    question_text: str
    question_intent: str
    question_source: str


class InterviewTurnCreate(BaseModel):
    action: Literal["interview", "regenerate_script"] = "interview"
    round_id: UUID | None = None
    answer_text: str | None = Field(default=None, max_length=50000)
    asset_ids: list[UUID] = Field(default_factory=list, max_length=12)
    idempotency_key: str = Field(min_length=8, max_length=180)


class InterviewTurnWorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    round_id: UUID
    chapter_id: UUID | None
    job_id: UUID | None
    idempotency_key: str
    status: str
    asset_ids: list[str]
    source_claim_ids: list[str]
    script_scene_ids: list[str]
    script_project_id: UUID | None
    next_question: str | None
    next_question_intent: str | None
    missing_topics: list[str]
    script_brief: dict
    error_code: str | None
    retry_allowed: bool = True
    retry_after_seconds: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class InterviewWorkspaceRead(BaseModel):
    session: InterviewSessionRead
    assets: list[SourceAssetRead] = Field(default_factory=list)
    script: ScriptProjectRead | None = None
    latest_workflow: InterviewTurnWorkflowRead | None = None

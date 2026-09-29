from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.interview import service
from lifereel_api.modules.interview.schemas import (
    ChapterRead,
    InterviewAnswer,
    InterviewRoundCreate,
    InterviewRoundRead,
    InterviewSessionRead,
    InterviewStart,
    NextQuestionRead,
)

router = APIRouter(tags=["interviews"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]


@router.get("/chapters", response_model=list[ChapterRead])
def chapters(db: Db, tenant_id: Tenant) -> list[ChapterRead]:
    return service.list_chapters(db, tenant_id)


@router.get("/interviews", response_model=list[InterviewSessionRead])
def interviews(db: Db, tenant_id: Tenant) -> list[InterviewSessionRead]:
    return service.list_sessions(db, tenant_id)


@router.post(
    "/interviews", response_model=InterviewSessionRead, status_code=status.HTTP_201_CREATED
)
def start_interview(payload: InterviewStart, db: Db, tenant_id: Tenant) -> InterviewSessionRead:
    return service.start_interview(db, tenant_id, payload)


@router.get("/interviews/{session_id}", response_model=InterviewSessionRead)
def interview(session_id: UUID, db: Db, tenant_id: Tenant) -> InterviewSessionRead:
    return service.get_session(db, tenant_id, session_id)


@router.post(
    "/interviews/{session_id}/rounds",
    response_model=InterviewRoundRead,
    status_code=status.HTTP_201_CREATED,
)
def create_round(
    session_id: UUID, payload: InterviewRoundCreate, db: Db, tenant_id: Tenant
) -> InterviewRoundRead:
    return service.add_round(db, tenant_id, session_id, payload)


@router.post("/interviews/{session_id}/rounds/{round_id}/answer", response_model=InterviewRoundRead)
def answer_round(
    session_id: UUID,
    round_id: UUID,
    payload: InterviewAnswer,
    db: Db,
    tenant_id: Tenant,
) -> InterviewRoundRead:
    return service.answer_round(
        db,
        tenant_id,
        session_id,
        round_id,
        payload.answer_text,
        payload.source_asset_id,
    )


@router.get("/interviews/{session_id}/next-question", response_model=NextQuestionRead)
def next_question(session_id: UUID, db: Db, tenant_id: Tenant) -> NextQuestionRead:
    return service.suggest_next_question(db, tenant_id, session_id)

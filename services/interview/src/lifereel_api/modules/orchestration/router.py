from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.interview.schemas import (
    InterviewTurnCreate,
    InterviewTurnWorkflowRead,
    InterviewWorkspaceRead,
)
from lifereel_api.modules.jobs.dispatch import require_execution_access
from lifereel_api.modules.orchestration import service

router = APIRouter(tags=["interview-orchestration"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]


@router.post(
    "/interviews/{session_id}/turns",
    response_model=InterviewTurnWorkflowRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_turn(
    session_id: UUID, payload: InterviewTurnCreate, db: Db, tenant_id: Tenant
) -> InterviewTurnWorkflowRead:
    return service.create_turn(db, tenant_id, session_id, payload)


@router.get(
    "/interviews/{session_id}/workspace",
    response_model=InterviewWorkspaceRead,
)
def workspace(session_id: UUID, db: Db, tenant_id: Tenant) -> InterviewWorkspaceRead:
    return service.get_workspace(db, tenant_id, session_id)


@router.post(
    "/internal/interview-turns/{workflow_id}/execute",
    response_model=InterviewTurnWorkflowRead,
    dependencies=[Depends(require_execution_access)],
)
def execute_turn(workflow_id: UUID, db: Db, tenant_id: Tenant) -> InterviewTurnWorkflowRead:
    return service.execute_turn(db, tenant_id, workflow_id)

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.script import service
from lifereel_api.modules.script.schemas import (
    ScriptGenerateRequest,
    ScriptProjectRead,
)

router = APIRouter(prefix="/scripts", tags=["scripts"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]


def to_read(project, scenes, shots) -> ScriptProjectRead:
    payload = ScriptProjectRead.model_validate(project)
    return payload.model_copy(update={"scenes": scenes, "shots": shots})


@router.get("", response_model=list[ScriptProjectRead])
def scripts(db: Db, tenant_id: Tenant) -> list[ScriptProjectRead]:
    projects = service.list_projects(db, tenant_id)
    return [to_read(*service.get_project(db, tenant_id, item.id)) for item in projects]


@router.post("/generate", response_model=ScriptProjectRead, status_code=status.HTTP_201_CREATED)
def generate_script(payload: ScriptGenerateRequest, db: Db, tenant_id: Tenant) -> ScriptProjectRead:
    project, scenes, shots = service.generate_draft(db, tenant_id, payload)
    return to_read(project, scenes, shots)


@router.get("/{project_id}", response_model=ScriptProjectRead)
def script(project_id: UUID, db: Db, tenant_id: Tenant) -> ScriptProjectRead:
    project, scenes, shots = service.get_project(db, tenant_id, project_id)
    return to_read(project, scenes, shots)

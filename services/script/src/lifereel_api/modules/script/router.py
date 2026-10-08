from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.evidence.schemas import SourceAssetRead
from lifereel_api.modules.interview.profile_models import LifeProfile
from lifereel_api.modules.script import queries, references, service
from lifereel_api.modules.script.models import ScriptProject
from lifereel_api.modules.script.schemas import (
    ScriptGenerateRequest,
    ScriptProjectRead,
    ScriptReferencesUpdate,
    ScriptSceneRead,
    ScriptSceneUpdate,
    ScriptShotRead,
)

router = APIRouter(prefix="/scripts", tags=["scripts"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]


def to_read(project, scenes, shots) -> ScriptProjectRead:
    payload = ScriptProjectRead.model_validate(project)
    return payload.model_copy(
        update={
            "scenes": [ScriptSceneRead.model_validate(scene) for scene in scenes],
            "shots": [ScriptShotRead.model_validate(shot) for shot in shots],
        }
    )


@router.get("", response_model=list[ScriptProjectRead])
def scripts(db: Db, tenant_id: Tenant, include_history: bool = False) -> list[ScriptProjectRead]:
    projects = (
        list(
            db.scalars(
                select(ScriptProject)
                .where(ScriptProject.tenant_id == tenant_id)
                .order_by(ScriptProject.created_at.desc())
            )
        )
        if include_history
        else service.list_projects(db, tenant_id)
    )
    return [
        with_freshness(db, tenant_id, to_read(*item))
        for item in queries.project_contents(db, tenant_id, projects)
    ]


@router.post("/generate", response_model=ScriptProjectRead, status_code=status.HTTP_201_CREATED)
def generate_script(payload: ScriptGenerateRequest, db: Db, tenant_id: Tenant) -> ScriptProjectRead:
    if not payload.book_revision_ids and db.scalar(
        select(LifeProfile.id).where(
            LifeProfile.tenant_id == tenant_id,
            LifeProfile.subject_id == payload.subject_id,
        )
    ):
        raise ApiError(409, ErrorCode.SCRIPT_BOOK_SOURCE_REQUIRED)
    project, scenes, shots = service.generate_draft(db, tenant_id, payload)
    return to_read(project, scenes, shots)


@router.get("/{project_id}", response_model=ScriptProjectRead)
def script(project_id: UUID, db: Db, tenant_id: Tenant) -> ScriptProjectRead:
    project, scenes, shots = service.get_project(db, tenant_id, project_id)
    return with_freshness(db, tenant_id, to_read(project, scenes, shots))


def with_freshness(db, tenant, result):
    if result.source_type != "book":
        return result
    from lifereel_api.modules.book.service import digest
    from lifereel_api.modules.script.book_adaptation import sources

    try:
        current = sources(
            db,
            tenant,
            result.subject_id,
            [UUID(r["revision_id"]) for r in result.source_snapshot.get("revisions", [])],
        )
        stale = digest(current) != digest(result.source_snapshot)
    except ApiError:
        stale = True
    return result.model_copy(update={"source_stale": stale})


@router.patch("/{project_id}/scenes/{scene_id}", response_model=ScriptProjectRead)
def update_scene(
    project_id: UUID,
    scene_id: UUID,
    payload: ScriptSceneUpdate,
    db: Db,
    tenant_id: Tenant,
) -> ScriptProjectRead:
    return to_read(*service.update_scene(db, tenant_id, project_id, scene_id, payload))


@router.get("/{project_id}/scenes/{scene_id}/references", response_model=list[SourceAssetRead])
def scene_references(project_id: UUID, scene_id: UUID, db: Db, tenant_id: Tenant):
    project, scene = references.get_scene(db, tenant_id, project_id, scene_id)
    return references.resolve(db, project, scene, strict=False)


@router.patch("/{project_id}/scenes/{scene_id}/references", response_model=ScriptProjectRead)
def update_references(
    project_id: UUID,
    scene_id: UUID,
    payload: ScriptReferencesUpdate,
    db: Db,
    tenant_id: Tenant,
):
    return to_read(*references.update(db, tenant_id, project_id, scene_id, payload))

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.memory import service
from lifereel_api.modules.memory.schemas import (
    MemoryClaimRead,
    MemoryCompileRequest,
    MemoryCompileResult,
    MemoryConflictRead,
    MemoryEntityRead,
    MemoryGraphRead,
    MemoryOverview,
    MemoryReviewRequest,
    TimelineAnchorRead,
)

router = APIRouter(prefix="/memories", tags=["memories"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]


@router.get("", response_model=list[MemoryClaimRead])
def memories(db: Db, tenant_id: Tenant, subject_id: UUID | None = None) -> list[MemoryClaimRead]:
    return service.list_claims(db, tenant_id, subject_id)


@router.post("/compile", response_model=MemoryCompileResult)
def compile_memory(payload: MemoryCompileRequest, db: Db, tenant_id: Tenant) -> MemoryCompileResult:
    created, existing, claims = service.compile_memories(db, tenant_id, payload)
    return MemoryCompileResult(
        created_count=created,
        existing_count=existing,
        claims=claims,
    )


@router.patch("/{claim_id}/review", response_model=MemoryClaimRead)
def review_memory(
    claim_id: UUID, payload: MemoryReviewRequest, db: Db, tenant_id: Tenant
) -> MemoryClaimRead:
    return service.review_claim(db, tenant_id, claim_id, payload.status)


@router.get("/subjects/{subject_id}/overview", response_model=MemoryOverview)
def overview(subject_id: UUID, db: Db, tenant_id: Tenant) -> MemoryOverview:
    return service.memory_overview(db, tenant_id, subject_id)


@router.get("/subjects/{subject_id}/entities", response_model=list[MemoryEntityRead])
def entities(subject_id: UUID, db: Db, tenant_id: Tenant) -> list[MemoryEntityRead]:
    return service.list_entities(db, tenant_id, subject_id)


@router.get("/subjects/{subject_id}/timeline", response_model=list[TimelineAnchorRead])
def timeline(subject_id: UUID, db: Db, tenant_id: Tenant) -> list[TimelineAnchorRead]:
    return service.list_timeline(db, tenant_id, subject_id)


@router.get("/subjects/{subject_id}/conflicts", response_model=list[MemoryConflictRead])
def conflicts(subject_id: UUID, db: Db, tenant_id: Tenant) -> list[MemoryConflictRead]:
    return service.list_conflicts(db, tenant_id, subject_id)


@router.get("/subjects/{subject_id}/graph", response_model=MemoryGraphRead)
def graph(subject_id: UUID, db: Db, tenant_id: Tenant) -> MemoryGraphRead:
    return service.memory_graph(db, tenant_id, subject_id)

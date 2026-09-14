from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.jobs import service
from lifereel_api.modules.jobs.dispatch import require_execution_access
from lifereel_api.modules.jobs.schemas import JobFailure, JobRead

router = APIRouter(prefix="/jobs", tags=["jobs"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]


@router.get("", response_model=list[JobRead])
def jobs(db: Db, tenant_id: Tenant) -> list[JobRead]:
    return service.list_jobs(db, tenant_id)


@router.get("/{job_id}", response_model=JobRead)
def job(job_id: UUID, db: Db, tenant_id: Tenant) -> JobRead:
    return service.get_job(db, tenant_id, job_id)


@router.post("/{job_id}/retry", response_model=JobRead)
def retry(job_id: UUID, db: Db, tenant_id: Tenant) -> JobRead:
    job = service.retry_job(db, tenant_id, job_id)
    try:
        service.enqueue(job)
    except Exception:
        service.fail_job(db, tenant_id, job.id, "WORKER_ERROR", None)
        raise ApiError(503, ErrorCode.WORKER_ERROR) from None
    return job


@router.post("/{job_id}/fail", response_model=JobRead,
             dependencies=[Depends(require_execution_access)])
def fail(job_id: UUID, payload: JobFailure, db: Db, tenant_id: Tenant) -> JobRead:
    return service.fail_job(
        db,
        tenant_id,
        job_id,
        payload.error_code,
        payload.error_message,
    )

from __future__ import annotations

import json
from uuid import UUID

import redis
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing import service as billing
from lifereel_api.modules.jobs.models import Job


def create_job(
    db: Session,
    tenant_id: UUID,
    kind: str,
    payload: dict,
    idempotency_key: str,
) -> tuple[Job, bool]:
    existing = db.scalar(
        select(Job).where(Job.tenant_id == tenant_id, Job.idempotency_key == idempotency_key)
    )
    if existing:
        return existing, False
    job = Job(
        tenant_id=tenant_id,
        kind=kind,
        status="queued",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    db.add(job)
    db.flush()
    return job, True


def list_jobs(db: Session, tenant_id: UUID) -> list[Job]:
    return list(
        db.scalars(select(Job).where(Job.tenant_id == tenant_id).order_by(Job.created_at.desc()))
    )


def get_job(db: Session, tenant_id: UUID, job_id: UUID) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id))
    if job is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.JOB_NOT_FOUND)
    return job


def retry_job(db: Session, tenant_id: UUID, job_id: UUID) -> Job:
    job = get_job(db, tenant_id, job_id)
    if job.kind == "production.render":
        from lifereel_api.modules.production.locking import execution_lock
        from lifereel_api.modules.production.models import ProductionRun

        run = db.scalar(
            select(ProductionRun).where(
                ProductionRun.tenant_id == tenant_id, ProductionRun.job_id == job.id
            )
        )
        if run is not None:
            with execution_lock(db, run.id) as acquired:
                if not acquired:
                    raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
                db.refresh(job)
                db.refresh(run)
                return _retry_job(db, tenant_id, job_id)
    return _retry_job(db, tenant_id, job_id)


def _retry_job(db: Session, tenant_id: UUID, job_id: UUID) -> Job:
    job = get_job(db, tenant_id, job_id)
    if job.status not in {"failed", "cancelled"}:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.JOB_RETRY_NOT_ALLOWED)
    if job.kind == "production.render":
        from lifereel_api.modules.production.models import ProductionRun

        run = db.scalar(
            select(ProductionRun).where(
                ProductionRun.tenant_id == tenant_id, ProductionRun.job_id == job.id
            )
        )
        if run is not None and run.status != "completed":
            billing.video_reserve(db, run)
            run.status = "queued"
            run.error_message = None
    if job.kind == "interview.turn.process":
        from lifereel_api.modules.interview.models import InterviewTurnWorkflow

        workflow = db.scalar(
            select(InterviewTurnWorkflow).where(
                InterviewTurnWorkflow.tenant_id == tenant_id,
                InterviewTurnWorkflow.job_id == job.id,
            )
        )
        if workflow is not None:
            workflow.status = "queued"
            workflow.error_code = None
    job.status = "queued"
    job.error_code = None
    job.error_message = None
    db.commit()
    db.refresh(job)
    return job


def fail_job(
    db: Session, tenant_id: UUID, job_id: UUID, error_code: str, error_message: str | None
) -> Job:
    job = get_job(db, tenant_id, job_id)
    if job.kind == "production.render":
        from lifereel_api.modules.production.locking import execution_lock
        from lifereel_api.modules.production.models import ProductionRun

        run = db.scalar(
            select(ProductionRun).where(
                ProductionRun.job_id == job.id, ProductionRun.tenant_id == tenant_id
            )
        )
        if run:
            with execution_lock(db, run.id) as acquired:
                if not acquired:
                    return job
                db.refresh(job)
                return _fail_job(db, tenant_id, job_id, error_code, error_message)
    return _fail_job(db, tenant_id, job_id, error_code, error_message)


def _fail_job(
    db: Session,
    tenant_id: UUID,
    job_id: UUID,
    error_code: str,
    error_message: str | None,
) -> Job:
    job = get_job(db, tenant_id, job_id)
    if job.status == "failed" and job.error_code and error_code == "WORKER_ERROR":
        return job
    if job.status != "completed":
        job.status = "failed"
        job.error_code = error_code
        job.error_message = (error_message or error_code)[:4000]
        if job.kind == "production.render":
            from lifereel_api.modules.production.models import ProductionRun

            run = db.scalar(
                select(ProductionRun).where(
                    ProductionRun.tenant_id == tenant_id, ProductionRun.job_id == job.id
                )
            )
            if run is not None and run.status != "completed":
                run.status = "failed"
                run.error_message = error_code
                billing.video_finish(db, run, False)
        db.commit()
        db.refresh(job)
    return job


def complete_job(db: Session, tenant_id: UUID, job_id: UUID, result: dict) -> Job:
    job = get_job(db, tenant_id, job_id)
    if job.status != "completed":
        job.status = "completed"
        job.result = result
        job.error_code = None
        job.error_message = None
        db.commit()
        db.refresh(job)
    return job


def enqueue(job: Job) -> None:
    settings = get_settings()
    client = redis.from_url(settings.redis_url, decode_responses=True)
    client.rpush(
        settings.worker_queue,
        json.dumps(
            {
                "job_id": str(job.id),
                "tenant_id": str(job.tenant_id),
                "kind": job.kind,
                "payload": job.payload,
            }
        ),
    )

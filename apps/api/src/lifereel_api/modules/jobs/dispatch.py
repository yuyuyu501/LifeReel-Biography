"""Database-backed queue: leases schedule work, execution locks fence side effects."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import get_db
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.production.locking import execution_lock

KINDS = {"interview": "interview.turn.process", "video": "production.render"}
ACTIVE = ("queued", "running")


def require_worker(x_worker_key: Annotated[str | None, Header()] = None):
    secret = get_settings().api_access_key
    if not secret:
        raise ApiError(503, ErrorCode.API_KEY_NOT_CONFIGURED)
    expected = hmac.new(secret.encode(), b"lifereel-worker-v1", hashlib.sha256).hexdigest()
    if not x_worker_key or not hmac.compare_digest(expected, x_worker_key):
        raise ApiError(401, ErrorCode.API_KEY_INVALID)


def require_execution_access(x_worker_key: Annotated[str | None, Header()] = None):
    if not get_settings().is_development:
        require_worker(x_worker_key)


router = APIRouter(prefix="/v1/internal/worker", dependencies=[Depends(require_worker)])
Db = Annotated[Session, Depends(get_db)]


class ClaimRequest(BaseModel):
    lane: Literal["interview", "video"]


class LeaseRequest(BaseModel):
    token: UUID


def claim_job(db: Session, lane: str):
    settings = get_settings()
    if settings.job_queue_backend != "database":
        raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
    now = datetime.now(UTC)
    kind = KINDS[lane]
    limit = settings.interview_concurrency if lane == "interview" else settings.video_concurrency
    # Serialise only admission to each lane, not its jobs or their AI calls.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": 910001 if lane == "interview" else 910002},
        )
    active = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(
            Job.kind == kind,
            Job.status.in_(ACTIVE),
            Job.lease_expires_at > now,
        )
    )
    if active >= limit:
        db.rollback()
        return None
    job = db.scalar(
        select(Job)
        .where(
            Job.kind == kind,
            Job.status.in_(ACTIVE),
            or_(Job.lease_expires_at.is_(None), Job.lease_expires_at <= now),
        )
        .order_by(Job.created_at, Job.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        db.rollback()
        return None
    job.lease_token = uuid4()
    job.lease_expires_at = now + timedelta(seconds=settings.job_lease_seconds)
    db.commit()
    return {"job_id": str(job.id), "token": str(job.lease_token)}


@router.post("/claim")
def claim(payload: ClaimRequest, db: Db):
    return claim_job(db, payload.lane)


@router.post("/{job_id}/heartbeat")
def heartbeat(job_id: UUID, payload: LeaseRequest, db: Db):
    result = db.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.lease_token == payload.token,
            Job.lease_expires_at > datetime.now(UTC),
        )
        .values(
            lease_expires_at=datetime.now(UTC)
            + timedelta(
                seconds=get_settings().job_lease_seconds,
            )
        )
    )
    db.commit()
    return {"owned": result.rowcount == 1}


@router.post("/{job_id}/release")
def release(job_id: UUID, payload: LeaseRequest, db: Db):
    # Never reset another consumer's lease. A running HTTP request may still finish.
    result = db.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.lease_token == payload.token,
        )
        .values(lease_expires_at=datetime.now(UTC) + timedelta(seconds=5))
    )
    db.commit()
    return {"owned": result.rowcount == 1}


def execute_claim(db: Session, job_id: UUID, token: UUID):
    from lifereel_api.modules.jobs import service as jobs
    from lifereel_api.modules.orchestration import service as interviews
    from lifereel_api.modules.production import service as production
    from lifereel_api.modules.production.models import ProductionRun

    with execution_lock(db, job_id) as acquired:
        if not acquired:
            return {"status": "running"}
        job = db.get(Job, job_id, populate_existing=True)
        if (
            job is None
            or job.lease_token != token
            or (
                job.lease_expires_at is None
                or job.lease_expires_at.replace(tzinfo=UTC) <= datetime.now(UTC)
            )
        ):
            raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
        if job.status not in ACTIVE:
            return {"status": job.status}
        try:
            if job.kind == KINDS["interview"]:
                interviews.execute_turn(
                    db, job.tenant_id, UUID(job.payload["workflow_id"]), recover_interrupted=True
                )
            elif job.kind == KINDS["video"]:
                run = db.scalar(
                    select(ProductionRun).where(
                        ProductionRun.job_id == job.id,
                        ProductionRun.tenant_id == job.tenant_id,
                    )
                )
                if run is None:
                    raise ApiError(404, ErrorCode.PRODUCTION_RUN_NOT_FOUND)
                production.execute_run(db, job.tenant_id, run.id)
            else:
                raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
        except Exception as exc:
            db.rollback()
            code = exc.code.value if isinstance(exc, ApiError) else "WORKER_ERROR"
            jobs.fail_job(db, job.tenant_id, job.id, code, None)
        db.refresh(job)
        return {"status": job.status}


@router.post("/{job_id}/execute")
def execute(job_id: UUID, payload: LeaseRequest, db: Db):
    return execute_claim(db, job_id, payload.token)

"""Durable photo redraw jobs shared by explicit edits and chapter preparation."""

import hashlib
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.evidence.models import SourceAsset
from lifereel_api.modules.evidence.service import get_asset
from lifereel_api.modules.evidence.storage import private_storage
from lifereel_api.modules.jobs import service as jobs
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.providers import siliconflow

KIND = "evidence.photo_redraw"


def validate_source(db: Session, tenant_id: UUID, asset_id: UUID) -> SourceAsset:
    asset = get_asset(db, tenant_id, asset_id)
    if (
        asset.kind != "photo" or asset.status != "ready" or asset.consent_status != "granted"
        or asset.derived_from_asset_id is not None or asset.mime_type not in siliconflow.MIMES
        or not 0 < asset.byte_size <= siliconflow.MAX_BYTES
    ):
        raise ApiError(422, ErrorCode.PHOTO_REDRAW_SOURCE_INVALID)
    return asset


def fingerprint(asset: SourceAsset) -> str:
    version = f"{siliconflow.MODEL}:{siliconflow.PROMPT}:{get_settings().photo_redraw_provider}"
    return f"redraw:{asset.id}:{asset.sha256}:{hashlib.sha256(version.encode()).hexdigest()[:16]}"


def current_job(db: Session, tenant_id: UUID, asset_id: UUID) -> Job | None:
    asset = get_asset(db, tenant_id, asset_id)
    return db.scalar(select(Job).where(
        Job.tenant_id == tenant_id, Job.kind == KIND, Job.idempotency_key == fingerprint(asset),
    ))


def create(db: Session, tenant_id: UUID, asset_id: UUID) -> Job:
    settings = get_settings()
    if (
        settings.job_queue_backend != "database"
        or settings.photo_redraw_provider == "disabled"
        or (settings.photo_redraw_provider == "mock" and not settings.is_development)
        or (settings.photo_redraw_provider == "siliconflow" and not settings.siliconflow_api_key)
    ):
        raise ApiError(503, ErrorCode.PHOTO_REDRAW_NOT_CONFIGURED)
    with execution_lock(db, asset_id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.RESOURCE_BUSY)
        source = validate_source(db, tenant_id, asset_id)
        job, _ = jobs.create_job(db, tenant_id, KIND, {
            "source_asset_id": str(source.id), "source_sha256": source.sha256,
            "subject_id": str(source.subject_id), "provider": settings.photo_redraw_provider,
            "model": siliconflow.MODEL, "prompt": siliconflow.PROMPT,
            "prompt_version": siliconflow.PROMPT_VERSION,
        }, fingerprint(source))
        db.commit()
        return job


def retry(db: Session, job: Job) -> Job:
    with execution_lock(db, job.id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
        db.refresh(job)
        reset_failed_job(db, job)
        db.commit()
        return job


def reset_failed_job(db: Session, job: Job) -> None:
    """Reset an explicitly retried job while its execution lock is held."""
    if (
        job.status != "failed" or job.attempt_count >= 3
        or job.error_code == ErrorCode.PHOTO_REDRAW_REJECTED
    ):
        raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
    validate_source(db, job.tenant_id, UUID(job.payload["source_asset_id"]))
    job.status, job.error_code, job.error_message = "queued", None, None
    job.result = None


def execute(db: Session, job: Job) -> None:
    # Called under the worker's job execution lock. Never auto-repeat an uncertain paid call.
    if job.status == "completed":
        return
    if (job.result or {}).get("request_started"):
        raise ApiError(409, ErrorCode.PHOTO_REDRAW_UNCERTAIN)
    source = validate_source(db, job.tenant_id, UUID(job.payload["source_asset_id"]))
    if (
        source.sha256 != job.payload["source_sha256"]
        or str(source.subject_id) != job.payload["subject_id"]
        or job.payload["provider"] != get_settings().photo_redraw_provider
        or job.payload["model"] != siliconflow.MODEL
        or job.payload["prompt"] != siliconflow.PROMPT
    ):
        raise ApiError(422, ErrorCode.PHOTO_REDRAW_SOURCE_INVALID)
    storage = private_storage()
    try:
        content = storage.get(source.storage_key)
    except (OSError, ValueError):
        raise ApiError(422, ErrorCode.PHOTO_REDRAW_SOURCE_INVALID) from None
    if (
        len(content) != source.byte_size or hashlib.sha256(content).hexdigest() != source.sha256
        or siliconflow.image_mime(content) != source.mime_type
    ):
        raise ApiError(422, ErrorCode.PHOTO_REDRAW_SOURCE_INVALID)
    job.status = "running"
    job.attempt_count += 1
    job.result = {"request_started": True}
    db.commit()
    output = siliconflow.redraw(content, source.mime_type)
    db.refresh(source)
    validate_source(db, job.tenant_id, source.id)
    if (
        source.sha256 != job.payload["source_sha256"]
        or str(source.subject_id) != job.payload["subject_id"]
    ):
        raise ApiError(422, ErrorCode.PHOTO_REDRAW_SOURCE_INVALID)
    digest = hashlib.sha256(output.content).hexdigest()
    existing = db.scalar(select(SourceAsset.id).where(
        SourceAsset.tenant_id == source.tenant_id, SourceAsset.subject_id == source.subject_id,
        SourceAsset.sha256 == digest,
    ))
    if existing:
        # Do not relabel an original or another source's derivative as this output.
        raise ApiError(502, ErrorCode.PHOTO_REDRAW_RESULT_INVALID)
    extension = siliconflow.MIMES[output.mime_type]
    key = (
        f"LifeReel-Biography/tenants/{source.tenant_id}/persons/{source.subject_id}/"
        f"redraw/{job.id}/{digest}.{extension}"
    )
    storage.put(key, output.content)
    derived = SourceAsset(
        tenant_id=source.tenant_id, subject_id=source.subject_id, chapter_id=source.chapter_id,
        derived_from_asset_id=source.id, kind="photo", status="ready",
        original_filename=f"{Path(source.original_filename).stem[:200]}-彩色转绘.{extension}",
        mime_type=output.mime_type, byte_size=len(output.content), sha256=digest, storage_key=key,
        consent_scope=source.consent_scope, consent_status=source.consent_status,
        analysis_status="not_applicable", metadata_json={
            "purpose": "photo_redraw", "synthetic": True, "video_reference_approved": False,
            "source_sha256": source.sha256, "job_id": str(job.id),
            "provider": job.payload["provider"], "model": siliconflow.MODEL,
            "prompt": siliconflow.PROMPT, "prompt_version": siliconflow.PROMPT_VERSION,
            "provider_trace_id": output.trace_id,
        },
    )
    db.add(derived)
    db.flush()
    job.status = "completed"
    job.result = {"asset_id": str(derived.id), "source_asset_id": str(source.id)}
    job.error_code = job.error_message = None
    db.commit()

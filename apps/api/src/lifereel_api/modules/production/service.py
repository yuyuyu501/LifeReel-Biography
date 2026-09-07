from __future__ import annotations

import hashlib
import logging
from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.evidence.storage import private_storage
from lifereel_api.modules.governance import service as governance
from lifereel_api.modules.identity.models import Person
from lifereel_api.modules.jobs import service as job_service
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.production.models import GeneratedAsset, ProductionRun
from lifereel_api.modules.production.providers import get_video_provider
from lifereel_api.modules.production.schemas import ProductionStart
from lifereel_api.modules.script.models import ScriptProject, ScriptScene

logger = logging.getLogger(__name__)


def start_production(db: Session, tenant_id: UUID, payload: ProductionStart) -> ProductionRun:
    provider_name = payload.provider or get_settings().video_provider
    project = db.scalar(
        select(ScriptProject).where(
            ScriptProject.id == payload.project_id, ScriptProject.tenant_id == tenant_id
        )
    )
    if project is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.SCRIPT_PROJECT_NOT_FOUND)
    scenes = list(
        db.scalars(
            select(ScriptScene)
            .where(ScriptScene.project_id == project.id)
            .order_by(ScriptScene.order_index)
        )
    )
    if not scenes:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.PRODUCTION_SCRIPT_EMPTY)
    subject = db.get(Person, project.subject_id)
    if (
        subject
        and subject.is_minor
        and not governance.has_consent(db, tenant_id, subject.id, "guardian", payload.audience)
    ):
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.GUARDIAN_CONSENT_REQUIRED)
    for consent_type in ("production", "portrait"):
        if not governance.has_consent(
            db, tenant_id, project.subject_id, consent_type, payload.audience
        ):
            consent_error = {
                "production": ErrorCode.PRODUCTION_CONSENT_REQUIRED,
                "portrait": ErrorCode.PORTRAIT_CONSENT_REQUIRED,
            }[consent_type]
            raise ApiError(status.HTTP_409_CONFLICT, consent_error)

    try:
        get_video_provider(provider_name)
    except ValueError as exc:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, ErrorCode.VIDEO_PROVIDER_INVALID
        ) from exc
    idempotency_key = (
        f"production:{project.id}:v{project.version_number}:{payload.audience}:{provider_name}"
    )
    job, created = job_service.create_job(
        db,
        tenant_id,
        "production.render",
        {
            "project_id": str(project.id),
            "audience": payload.audience,
            "provider": provider_name,
        },
        idempotency_key,
    )
    if not created:
        existing = db.scalar(
            select(ProductionRun).where(
                ProductionRun.tenant_id == tenant_id,
                ProductionRun.job_id == job.id,
            )
        )
        if existing:
            return existing
    run = ProductionRun(
        tenant_id=tenant_id,
        project_id=project.id,
        job_id=job.id,
        status="queued",
        provider=provider_name,
        audience=payload.audience,
        estimated_cost=0.0 if provider_name == "mock" else len(scenes) * 1.0,
    )
    db.add(run)
    db.flush()
    if provider_name != "mock" or not get_settings().execute_mock_jobs_inline:
        db.commit()
        job_service.enqueue(job)
        db.refresh(run)
        return run
    return execute_run(db, tenant_id, run.id)


def execute_run(db: Session, tenant_id: UUID, run_id: UUID) -> ProductionRun:
    run = db.scalar(
        select(ProductionRun).where(
            ProductionRun.id == run_id, ProductionRun.tenant_id == tenant_id
        )
    )
    if run is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.PRODUCTION_RUN_NOT_FOUND)
    if run.status == "completed":
        return run
    project = db.get(ScriptProject, run.project_id)
    job = db.get(Job, run.job_id) if run.job_id else None
    if project is None or job is None:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.PRODUCTION_STATE_INVALID)
    scenes = list(
        db.scalars(
            select(ScriptScene)
            .where(ScriptScene.project_id == project.id)
            .order_by(ScriptScene.order_index)
        )
    )
    run.status = "running"
    job.status = "running"
    job.attempt_count += 1
    try:
        provider = get_video_provider(run.provider)
        output = provider.render(
            project.title,
            [
                {
                    "heading": scene.heading,
                    "narration": scene.narration,
                    "visual_prompt": scene.visual_prompt,
                    "duration_seconds": scene.duration_seconds,
                    "source_claim_ids": scene.source_claim_ids,
                }
                for scene in scenes
            ],
        )
        digest = hashlib.sha256(output.content).hexdigest()
        storage_key = f"{tenant_id}/generated/{run.id}/{digest}.{output.extension}"
        private_storage().put(storage_key, output.content)
        asset = GeneratedAsset(
            tenant_id=tenant_id,
            production_run_id=run.id,
            scene_id=None,
            kind="final_video_manifest" if output.extension == "json" else "final_video",
            provider=run.provider,
            mime_type=output.mime_type,
            storage_key=storage_key,
            sha256=digest,
            generation_parameters=output.parameters,
        )
        db.add(asset)
        db.flush()
        run.status = "completed"
        run.error_message = None
        run.output_manifest = {
            "asset_id": str(asset.id),
            "sha256": digest,
            "mime_type": output.mime_type,
        }
        governance.audit(
            db, tenant_id, "production.completed", "production_run", run.id, run.output_manifest
        )
        job.status = "completed"
        job.result = {"production_run_id": str(run.id), **run.output_manifest}
    except Exception as exc:
        logger.exception("Video production failed for run %s", run.id, exc_info=exc)
        run.status = "failed"
        run.error_message = ErrorCode.VIDEO_PROVIDER_FAILED.value
        job.status = "failed"
        job.error_code = ErrorCode.VIDEO_PROVIDER_FAILED.value
        job.error_message = ErrorCode.VIDEO_PROVIDER_FAILED.value
    db.commit()
    db.refresh(run)
    return run


def list_runs(db: Session, tenant_id: UUID) -> list[ProductionRun]:
    return list(
        db.scalars(
            select(ProductionRun)
            .where(ProductionRun.tenant_id == tenant_id)
            .order_by(ProductionRun.created_at.desc())
        )
    )


def get_run_payload(
    db: Session, tenant_id: UUID, run_id: UUID
) -> tuple[ProductionRun, list[GeneratedAsset]]:
    run = db.scalar(
        select(ProductionRun).where(
            ProductionRun.id == run_id, ProductionRun.tenant_id == tenant_id
        )
    )
    if run is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.PRODUCTION_RUN_NOT_FOUND)
    assets = list(
        db.scalars(select(GeneratedAsset).where(GeneratedAsset.production_run_id == run.id))
    )
    return run, assets

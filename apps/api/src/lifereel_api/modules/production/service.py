from __future__ import annotations

import hashlib
import json
import logging
from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing import service as billing
from lifereel_api.modules.billing.usage import track_usage
from lifereel_api.modules.evidence.storage import private_storage
from lifereel_api.modules.governance import service as governance
from lifereel_api.modules.identity.models import Person
from lifereel_api.modules.jobs import service as job_service
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.production import segmented
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.modules.production.models import GeneratedAsset, ProductionRun
from lifereel_api.modules.production.planning import segment_durations
from lifereel_api.modules.production.providers import VideoProviderError, get_video_provider
from lifereel_api.modules.production.schemas import ProductionStart
from lifereel_api.modules.script.models import ScriptProject, ScriptScene

logger = logging.getLogger(__name__)


def start_production(db: Session, tenant_id: UUID, payload: ProductionStart) -> ProductionRun:
    billing.lock_wallet(db, tenant_id)
    settings = get_settings()
    provider_name = payload.provider or settings.video_provider
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
    if payload.scene_id:
        scenes = [scene for scene in scenes if scene.id == payload.scene_id]
    if not scenes:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.PRODUCTION_SCRIPT_EMPTY)
    config = None
    if provider_name in {"volcengine-seedance", "volcengine-seedance-1.5"}:
        config = {
            "model": settings.volcengine_video_model,
            "resolution": settings.volcengine_video_resolution,
            "ratio": settings.volcengine_video_ratio,
            "generate_audio": settings.volcengine_video_generate_audio,
            "watermark": settings.volcengine_video_watermark,
            "duration": settings.volcengine_video_duration,
            "mode": (
                "segmented"
                if settings.volcengine_video_model.startswith("doubao-seedance-2-")
                else "single_clip"
            ),
        }
        if config["mode"] == "segmented":
            try:
                counts = [len(segment_durations(scene.duration_seconds)) for scene in scenes]
                if sum(counts) > 24:
                    raise VideoProviderError("VIDEO_DURATION_UNSUPPORTED")
            except VideoProviderError as exc:
                raise ApiError(422, ErrorCode.VIDEO_DURATION_UNSUPPORTED) from exc
    snapshot = [
        {
            "id": str(scene.id),
            "chapter_id": str(scene.chapter_id) if scene.chapter_id else None,
            "order_index": scene.order_index,
            "heading": scene.heading,
            "narration": scene.narration,
            "visual_prompt": scene.visual_prompt,
            "duration_seconds": scene.duration_seconds,
            "source_claim_ids": scene.source_claim_ids,
        }
        for scene in scenes
    ]
    try:
        get_video_provider(provider_name)
    except VideoProviderError as exc:
        error_code = (
            ErrorCode.VIDEO_PROVIDER_CONFIGURATION_INCOMPLETE
            if exc.code == ErrorCode.VIDEO_PROVIDER_CONFIGURATION_INCOMPLETE.value
            else ErrorCode.VIDEO_PROVIDER_INVALID
        )
        raise ApiError(status.HTTP_503_SERVICE_UNAVAILABLE, error_code) from exc
    except ValueError as exc:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, ErrorCode.VIDEO_PROVIDER_INVALID
        ) from exc
    idempotency_key = (
        f"production:{project.id}:v{project.version_number}:{payload.audience}:{provider_name}"
    )
    if payload.scene_id:
        idempotency_key += f":scene:{payload.scene_id}"
    if config:
        fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]
        idempotency_key += f":{fingerprint}"
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
    subject = db.get(Person, project.subject_id)
    token_video = settings.billing_video_mode == "tokens" and provider_name != "mock"
    if token_video:
        from lifereel_api.modules.billing.video import validate_config

        validate_config(config or {})
        if len(scenes) != 1 or not 15 <= scenes[0].duration_seconds <= 30:
            raise ApiError(422, ErrorCode.VIDEO_DURATION_UNSUPPORTED)
    target_seconds = (
        config["duration"]
        if config and config["mode"] == "single_clip"
        else sum(scene.duration_seconds for scene in scenes)
    )
    quote = {
        **billing.prices(),
        "target_seconds": target_seconds,
        "video_billing_mode": "tokens" if token_video else "per_second",
        "amount_cents": (
            settings.billing_video_reserve_cents if token_video
            else target_seconds * settings.billing_video_cents_per_second
        ),
        "title": f"{subject.preferred_name or subject.display_name} · "
        + "、".join(scene.heading for scene in scenes),
    }
    if (
        payload.quoted_amount_cents is not None
        and payload.quoted_amount_cents != quote["amount_cents"]
    ):
        raise ApiError(409, ErrorCode.BILLING_QUOTE_CHANGED)
    run = ProductionRun(
        tenant_id=tenant_id,
        project_id=project.id,
        job_id=job.id,
        status="queued",
        provider=provider_name,
        audience=payload.audience,
        estimated_cost=0.0,
        output_manifest={
            "billing_quote": quote,
            "scene_id": str(payload.scene_id) if payload.scene_id else None,
            "script_version": project.version_number,
            "script_snapshot": snapshot,
            "generation_config": config,
            "subject": {
                "display_name": subject.display_name,
                "preferred_name": subject.preferred_name,
                "birth_year": subject.birth_year,
                "relation_to_owner": subject.relation_to_owner,
            }
            if subject
            else {},
        },
    )
    db.add(run)
    db.flush()
    billing.video_reserve(db, run)
    if provider_name != "mock" or not get_settings().execute_mock_jobs_inline:
        db.commit()
        try:
            job_service.enqueue(job)
        except Exception:
            job_service.fail_job(db, tenant_id, job.id, "WORKER_ERROR", None)
            raise ApiError(503, ErrorCode.WORKER_ERROR) from None
        db.refresh(run)
        return run
    return execute_run(db, tenant_id, run.id)


@track_usage("video")
def execute_run(db: Session, tenant_id: UUID, run_id: UUID) -> ProductionRun:
    with execution_lock(db, run_id) as acquired:
        if not acquired:
            return get_run_payload(db, tenant_id, run_id)[0]
        return _execute_run(db, tenant_id, run_id)


def _execute_run(db: Session, tenant_id: UUID, run_id: UUID) -> ProductionRun:
    run = db.scalar(
        select(ProductionRun).where(
            ProductionRun.id == run_id, ProductionRun.tenant_id == tenant_id
        )
    )
    if run is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.PRODUCTION_RUN_NOT_FOUND)
    if run.status == "completed":
        return run
    from lifereel_api.modules.production.recovery import assert_retry_allowed

    assert_retry_allowed(run)
    project = db.get(ScriptProject, run.project_id)
    job = db.get(Job, run.job_id) if run.job_id else None
    if project is None or job is None:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.PRODUCTION_STATE_INVALID)
    billing.video_reserve(db, run)
    scenes = list(
        db.scalars(
            select(ScriptScene)
            .where(ScriptScene.project_id == project.id)
            .order_by(ScriptScene.order_index)
        )
    )
    run.status = "running"
    run.error_message = None
    job.status = "running"
    job.error_code = None
    job.error_message = None
    job.attempt_count += 1
    db.commit()
    try:
        manifest = run.output_manifest or {}
        snapshot = manifest.get("script_snapshot")
        config = manifest.get("generation_config") or {}
        if config.get("mode") == "segmented":
            output = segmented.advance(db, run)
            if output is None:
                job_service.enqueue(job)
                return run
            manifest = run.output_manifest or {}
        else:
            provider = get_video_provider(run.provider)
            if config:
                for key in (
                    "model",
                    "resolution",
                    "ratio",
                    "duration",
                    "generate_audio",
                    "watermark",
                ):
                    setattr(provider, key, config[key])
            output = provider.render(
                snapshot[0]["heading"] if snapshot and len(snapshot) == 1 else project.title,
                snapshot
                if snapshot is not None
                else [
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
        storage_key = (
            f"LifeReel-Biography/generated/{tenant_id}/{run.id}/"
            f"{digest}.{output.extension}"
        )
        private_storage().put(storage_key, output.content)
        asset = GeneratedAsset(
            tenant_id=tenant_id,
            production_run_id=run.id,
            scene_id=(
                UUID(manifest["scene_id"])
                if manifest.get("scene_id")
                and any(str(scene.id) == manifest["scene_id"] for scene in scenes)
                else None
            ),
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
            **manifest,
            "asset_id": str(asset.id),
            "sha256": digest,
            "mime_type": output.mime_type,
        }
        governance.audit(
            db, tenant_id, "production.completed", "production_run", run.id, run.output_manifest
        )
        job.status = "completed"
        job.error_code = None
        job.error_message = None
        job.result = {"production_run_id": str(run.id), **run.output_manifest}
        billing.video_finish(db, run, True)
        job.result = {"production_run_id": str(run.id), **run.output_manifest}
    except Exception as exc:
        logger.exception("Video production failed for run %s", run_id, exc_info=exc)
        # Keep committed segment checkpoints, but never publish partially saved results.
        db.rollback()
        db.refresh(run)
        db.refresh(job)
        provider_code = getattr(exc, "code", ErrorCode.VIDEO_PROVIDER_FAILED.value)
        known_provider_codes = {
            ErrorCode.VIDEO_PROVIDER_CONFIGURATION_INCOMPLETE.value,
            ErrorCode.VIDEO_PROVIDER_REQUEST_FAILED.value,
            ErrorCode.VIDEO_PROVIDER_TIMEOUT.value,
            ErrorCode.VIDEO_PROVIDER_OUTPUT_INVALID.value,
            ErrorCode.VIDEO_PROVIDER_FAILED.value,
            ErrorCode.VIDEO_REFERENCE_REJECTED.value,
            ErrorCode.VIDEO_CONTENT_REJECTED.value,
            ErrorCode.VIDEO_REFERENCE_INVALID.value,
            ErrorCode.VIDEO_PLAN_FAILED.value,
            ErrorCode.VIDEO_PLAN_INVALID.value,
            ErrorCode.VIDEO_PLAN_CONFIGURATION_INCOMPLETE.value,
            ErrorCode.VIDEO_ASSEMBLY_UNAVAILABLE.value,
            ErrorCode.VIDEO_ASSEMBLY_FAILED.value,
            ErrorCode.VIDEO_DURATION_UNSUPPORTED.value,
            ErrorCode.VIDEO_DURATION_MISMATCH.value,
            ErrorCode.VIDEO_SUBMISSION_UNCERTAIN.value,
        }
        error_code = (
            provider_code
            if provider_code in known_provider_codes
            else ErrorCode.VIDEO_PROVIDER_FAILED.value
        )
        run.status = "failed"
        run.error_message = error_code
        job.status = "failed"
        job.error_code = error_code
        job.error_message = error_code
        billing.video_finish(db, run, False)
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

"""Regenerate one frozen shot into a new run, keeping source media and receipts."""

import copy
import hashlib
import tempfile
from uuid import UUID

from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing import service as billing
from lifereel_api.modules.evidence.storage import private_storage
from lifereel_api.modules.jobs import service as jobs
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.modules.production.models import ProductionRun
from lifereel_api.modules.production.providers import VideoProviderError
from lifereel_api.modules.production.reference_models import ChapterReferencePackage
from lifereel_api.modules.script.models import ScriptProject


def source_run(db, tenant_id, run_id, index):
    run = db.get(ProductionRun, run_id)
    if not run or run.tenant_id != tenant_id:
        raise ApiError(404, ErrorCode.PRODUCTION_RUN_NOT_FOUND)
    manifest = run.output_manifest or {}
    segments = manifest.get("segments") or []
    project = db.get(ScriptProject, run.project_id)
    if (
        run.status != "completed"
        or manifest.get("media_retention")
        or (manifest.get("generation_config") or {}).get("mode") != "segmented"
        or not 0 <= index < len(segments)
        or not project
        or project.version_number != manifest.get("script_version")
        or not manifest.get("plan")
        or len(manifest["plan"]["segments"]) != len(segments)
        or any(s.get("status") != "completed" for s in segments)
    ):
        raise ApiError(409, ErrorCode.PRODUCTION_STATE_INVALID)
    return run, project


def quote(db, tenant_id, run_id, index):
    run, project = source_run(db, tenant_id, run_id, index)
    settings = get_settings()
    seconds = run.output_manifest["segments"][index]["duration_seconds"]
    token_video = settings.billing_video_mode == "tokens" and run.provider != "mock"
    if token_video:
        from lifereel_api.modules.billing.video import validate_config

        validate_config(run.output_manifest["generation_config"])
    return {
        **billing.prices(),
        "target_seconds": seconds,
        "video_billing_mode": "tokens" if token_video else "per_second",
        "amount_cents": settings.billing_video_reserve_cents
        if token_video
        else seconds * settings.billing_video_cents_per_second,
        "title": f"局部重做 · 第{index + 1}镜头",
        "script_version": project.version_number,
    }


def start(db, tenant_id, run_id, index, payload):
    billing.lock_wallet(db, tenant_id)
    key = f"production-shot:{tenant_id}:{payload.request_id}"
    request = {
        "source_run_id": str(run_id),
        "segment_index": index,
        "script_version": payload.expected_script_version,
        "quoted_amount_cents": payload.quoted_amount_cents,
    }
    existing_job = db.scalar(
        select(Job).where(Job.tenant_id == tenant_id, Job.idempotency_key == key)
    )
    if existing_job:
        if existing_job.payload.get("regeneration_request") != request:
            raise ApiError(409, ErrorCode.PRODUCTION_STATE_INVALID)
        existing = db.scalar(
            select(ProductionRun).where(
                ProductionRun.tenant_id == tenant_id, ProductionRun.job_id == existing_job.id
            )
        )
        if existing:
            return existing
        raise ApiError(409, ErrorCode.PRODUCTION_STATE_INVALID)
    with execution_lock(db, run_id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.PRODUCTION_STATE_INVALID)
        source, project = source_run(db, tenant_id, run_id, index)
        price = quote(db, tenant_id, run_id, index)
        if price["script_version"] != payload.expected_script_version:
            raise ApiError(409, ErrorCode.PRODUCTION_STATE_INVALID)
        if price["amount_cents"] != payload.quoted_amount_cents:
            raise ApiError(409, ErrorCode.BILLING_QUOTE_CHANGED)
        job, _ = jobs.create_job(
            db,
            tenant_id,
            "production.render",
            {
                "project_id": str(project.id),
                "provider": source.provider,
                "audience": source.audience,
                "regeneration_request": request,
            },
            key,
        )
        original = copy.deepcopy(source.output_manifest)
        keep = (
            "scene_id",
            "script_version",
            "script_snapshot",
            "generation_config",
            "reference_package",
            "subject",
            "plan",
            "target_duration_seconds",
            "prepared_references",
        )
        manifest = {k: original[k] for k in keep if k in original}
        manifest.update(
            {
                "billing_quote": price,
                "stage": "copying_segments",
                "regeneration": {"source_run_id": str(run_id), "segment_index": index},
                "completed_segments": 0,
                "segments": [],
            }
        )
        for i, item in enumerate(original["segments"]):
            if i == index:
                segment = {**copy.deepcopy(original["plan"]["segments"][i]), "status": "pending"}
            else:
                segment = {**item, "status": "copy_pending", "reused": True}
            manifest["segments"].append(segment)
        run = ProductionRun(
            tenant_id=tenant_id,
            project_id=project.id,
            job_id=job.id,
            status="queued",
            provider=source.provider,
            audience=source.audience,
            estimated_cost=0,
            output_manifest=manifest,
        )
        db.add(run)
        db.flush()
        db.add(
            ChapterReferencePackage(
                tenant_id=tenant_id,
                production_run_id=run.id,
                subject_id=project.subject_id,
                chapter_id=UUID(manifest["reference_package"]["chapter_id"])
                if manifest.get("reference_package", {}).get("chapter_id")
                else None,
                payload=manifest.get("reference_package", {}),
            )
        )
        billing.video_reserve(db, run)
        db.commit()
    try:
        jobs.enqueue(job)
    except Exception:
        jobs.fail_job(db, tenant_id, job.id, "WORKER_ERROR", None)
        raise ApiError(503, ErrorCode.WORKER_ERROR) from None
    db.refresh(run)
    return run


def copy_media(storage, key, destination, expected_hash):
    digest = hashlib.sha256()
    with tempfile.TemporaryFile() as file:
        size = storage.size(key)
        if size <= 0:
            raise VideoProviderError("VIDEO_REFERENCE_INVALID")
        for part in storage.iter_range(key, 0, size - 1):
            digest.update(part)
            file.write(part)
        if expected_hash and digest.hexdigest() != expected_hash:
            raise VideoProviderError("VIDEO_REFERENCE_INVALID")
        file.seek(0)
        storage.put_file(destination, file)
    return digest.hexdigest()


def copy_next(db, run, manifest):
    """Copy one reused clip per queue delivery without holding the wallet lock."""
    pending = next(
        (
            (i, s)
            for i, s in enumerate(manifest.get("segments", []))
            if s.get("status") == "copy_pending"
        ),
        None,
    )
    if not pending:
        return False
    index, target = pending
    source_id = UUID(manifest["regeneration"]["source_run_id"])
    with execution_lock(db, source_id) as acquired:
        if not acquired:
            return True
        source = db.get(ProductionRun, source_id)
        if (
            not source
            or source.tenant_id != run.tenant_id
            or (source.output_manifest or {}).get("media_retention")
        ):
            raise VideoProviderError("VIDEO_REFERENCE_INVALID")
        storage = private_storage()
        prefix = f"LifeReel-Biography/generated/{run.tenant_id}/"
        old = prefix + str(source_id) + "/"
        new = prefix + str(run.id) + "/"
        if target.get("storage_key") != old + f"segment-{index}.mp4":
            raise VideoProviderError("VIDEO_REFERENCE_INVALID")
        target["sha256"] = copy_media(
            storage,
            target["storage_key"],
            new + f"segment-{index}.mp4",
            target.get("sha256")
            or (target.get("parameters", {}).get("original") or {}).get("sha256"),
        )
        target["storage_key"] = new + f"segment-{index}.mp4"
        tail = target.get("official_tail")
        if tail:
            suffix = f"originals/{index}-{tail['sha256']}"
            if tail.get("storage_key") != old + suffix:
                raise VideoProviderError("VIDEO_REFERENCE_INVALID")
            copy_media(storage, old + suffix, new + suffix, tail["sha256"])
            tail["storage_key"] = new + suffix
        for frame in target.get("review_frames", []):
            suffix = f"review/{index}-{frame['position']}.jpg"
            if frame.get("storage_key") != old + suffix:
                raise VideoProviderError("VIDEO_REFERENCE_INVALID")
            copy_media(storage, old + suffix, new + suffix, frame["sha256"])
            frame["storage_key"] = new + suffix
        target["status"] = "completed"
        manifest["completed_segments"] = sum(
            s["status"] == "completed" for s in manifest["segments"]
        )
        if all(s["status"] != "copy_pending" for s in manifest["segments"]):
            manifest["stage"] = "generating"
        run.output_manifest = copy.deepcopy(manifest)
        db.commit()
    return True

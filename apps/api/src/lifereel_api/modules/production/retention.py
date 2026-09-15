"""Replace chapter media only after a newer successful render is durable."""

import logging
from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, select

from lifereel_api.core.models import utcnow
from lifereel_api.modules.evidence.storage import private_storage
from lifereel_api.modules.jobs.service import create_job
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.modules.production.models import GeneratedAsset, ProductionRun
from lifereel_api.modules.publication.models import Publication

KIND = "production.cleanup"
logger = logging.getLogger(__name__)


def chapter_key(run):
    manifest = run.output_manifest or {}
    snapshot = manifest.get("script_snapshot") or []
    if len(snapshot) == 1 and snapshot[0].get("chapter_id"):
        return "chapter:" + snapshot[0]["chapter_id"]
    if manifest.get("scene_id"):
        return "scene:" + manifest["scene_id"]
    # Ambiguous legacy whole-book videos are never deleted by guessing a chapter.
    return None


def schedule(db, run):
    return create_job(db, run.tenant_id, KIND, {"project_id": str(run.project_id)},
                      f"media-retention:{run.id}")[0]


def is_retired(run):
    return bool((run.output_manifest or {}).get("media_retention"))


def cleanup_project(db, tenant_id, project_id):
    runs = list(db.scalars(select(ProductionRun).where(
        ProductionRun.tenant_id == tenant_id, ProductionRun.project_id == project_id,
    ).order_by(ProductionRun.created_at.desc(), ProductionRun.id.desc())))
    winners = {}
    for run in runs:
        key = chapter_key(run)
        if not key:
            continue
        if key not in winners:
            final = db.scalar(select(GeneratedAsset.id).where(
                GeneratedAsset.production_run_id == run.id,
                GeneratedAsset.kind.in_(["final_video", "final_video_manifest"]),
            ))
            if run.status == "completed" and not is_retired(run) and final:
                winners[key] = run.id
            continue
        with execution_lock(db, run.id) as acquired:
            if not acquired:
                raise RuntimeError("MEDIA_RETENTION_BUSY")
            db.refresh(run, with_for_update=True)
            manifest = run.output_manifest or {}
            if run.status not in {"completed", "failed", "cancelled"}:
                raise RuntimeError("MEDIA_RETENTION_BUSY")
            if (manifest.get("billing") or {}).get("status") == "pending":
                raise RuntimeError("MEDIA_RETENTION_UNSETTLED")
            retention = manifest.get("media_retention")
            if retention and retention.get("status") == "deleted":
                continue
            if not retention:
                assets = list(db.scalars(select(GeneratedAsset).where(
                    GeneratedAsset.production_run_id == run.id,
                )))
                keys = {asset.storage_key for asset in assets}
                for segment in manifest.get("segments", []):
                    if segment.get("storage_key"):
                        keys.add(segment["storage_key"])
                    tail = segment.get("official_tail") or {}
                    if tail.get("storage_key"):
                        keys.add(tail["storage_key"])
                prefix = f"LifeReel-Biography/generated/{tenant_id}/{run.id}/"
                if any(not key.startswith(prefix) or ".." in key or "\\" in key for key in keys):
                    raise ValueError("MEDIA_RETENTION_KEY_INVALID")
                retention = {"status": "pending", "replaced_by": str(winners[key]),
                             "keys": sorted(keys), "requested_at": utcnow().isoformat()}
                run.output_manifest = {**manifest, "media_retention": retention}
                for publication in db.scalars(select(Publication).where(
                    Publication.production_run_id == run.id, Publication.status == "published",
                )):
                    publication.status = "withdrawn"
                    publication.withdrawn_at = utcnow()
                db.commit()
            storage = private_storage()
            for storage_key in retention["keys"]:
                storage.delete(storage_key)
            db.execute(delete(GeneratedAsset).where(GeneratedAsset.production_run_id == run.id))
            run.output_manifest = {**run.output_manifest, "media_retention": {
                **retention, "status": "deleted", "deleted_at": utcnow().isoformat(),
            }}
            db.commit()


def execute_cleanup(db, job):
    job.attempt_count += 1
    db.commit()
    try:
        cleanup_project(db, job.tenant_id, UUID(job.payload["project_id"]))
        job.status = "completed"
        job.error_code = None
        job.result = {"media_cleanup": "completed"}
    except Exception:
        db.rollback()
        db.refresh(job)
        logger.exception("Media cleanup deferred for job %s", job.id)
        job.status = "queued"
        job.error_code = "MEDIA_CLEANUP_DEFERRED"
        job.lease_token = None
        job.lease_expires_at = utcnow() + timedelta(seconds=min(3600, 60 * job.attempt_count))
    db.commit()

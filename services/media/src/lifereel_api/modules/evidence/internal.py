from uuid import UUID

from lifereel_api.modules.evidence import service


def analyze(db, tenant, data):
    result = service.analyze_asset(db, tenant, UUID(data["asset_id"]))
    return {"observation_id": str(result.id)}


def retry(db, tenant, data):
    from lifereel_api.core.errors import ApiError, ErrorCode
    from lifereel_api.modules.jobs import service as jobs

    job = jobs.get_job(db, tenant, UUID(data["job_id"]))
    if job.kind not in {
        "production.render",
        "production.cleanup",
        "photo.restoration",
        "evidence.photo_redraw",
    }:
        raise ApiError(403, ErrorCode.AUTH_READ_ONLY)
    jobs.retry_job(
        db,
        tenant,
        job.id,
        reference_asset_id=UUID(data["reference_asset_id"])
        if data.get("reference_asset_id")
        else None,
        resume_original=data.get("resume_original", False),
    )
    return {"job_id": str(job.id)}


OPERATIONS = {
    "evidence.analyze": ({"interview", "worker-interview"}, analyze),
    "jobs.retry": ({"tasks"}, retry),
}

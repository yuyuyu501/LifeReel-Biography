from uuid import UUID

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.jobs import service


def retry(db, tenant, data):
    job = service.get_job(db, tenant, UUID(data["job_id"]))
    if job.kind != "interview.turn.process":
        raise ApiError(403, ErrorCode.AUTH_READ_ONLY)
    service.retry_job(db, tenant, job.id)
    return {"job_id": str(job.id)}


OPERATIONS = {"jobs.retry": ({"tasks"}, retry)}

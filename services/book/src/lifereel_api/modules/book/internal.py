from uuid import UUID

from lifereel_api.modules.book import service
from lifereel_api.modules.jobs.service import get_job


def retry(db, tenant, data):
    job = get_job(db, tenant, UUID(data["job_id"]))
    service.retry(db, job)
    return {"job_id": str(job.id)}


OPERATIONS = {"jobs.retry": ({"tasks"}, retry)}

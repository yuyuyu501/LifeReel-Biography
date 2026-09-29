"""Execute locally while a separate thread renews the fenced lease."""

from threading import Event, Thread
from uuid import UUID

from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.jobs.dispatch import LeaseRequest, execute_claim, heartbeat, release


def renew(job_id, token, done, touch):
    while not done.wait(20):
        try:
            with SessionLocal() as db:
                owned = heartbeat(job_id, LeaseRequest(token=token), db)["owned"]
            if not owned:
                return
            touch()
        except Exception:
            # Lost DB contact makes health stale. Expiry allows fenced recovery.
            pass


def process_claim(claim, touch):
    job_id, token = UUID(claim["job_id"]), UUID(claim["token"])
    done = Event()
    thread = Thread(target=renew, args=(job_id, token, done, touch), daemon=True)
    thread.start()
    try:
        with SessionLocal() as db:
            result = execute_claim(db, job_id, token)
        touch()
        if result["status"] in {"completed", "failed", "cancelled"}:
            with SessionLocal() as db:
                release(job_id, LeaseRequest(token=token), db)
        return result
    finally:
        # An exception or uncertain result must not release a potentially live job.
        done.set()
        thread.join(timeout=5)

"""Transactional database inbox; duplicate publication cannot schedule a job twice."""

from datetime import UTC, datetime

from sqlalchemy import select

from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.jobs.events import JobDelivery, OutboxEvent
from lifereel_api.modules.jobs.models import Job


def dispatch_batch(limit=50):
    published = 0
    with SessionLocal() as db:
        events = list(
            db.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.status == "pending",
                )
                .order_by(OutboxEvent.occurred_at, OutboxEvent.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for event in events:
            try:
                with db.begin_nested():
                    if event.event_type == "profile.sync.requested":
                        from lifereel_api.architecture.internal import call

                        call(
                            "memory",
                            "memory.profile-sync",
                            event.tenant_id,
                            event.payload,
                            timeout=30,
                        )
                    elif event.event_type.startswith("billing."):
                        from lifereel_api.architecture.internal import call

                        call(
                            "billing",
                            "billing.command",
                            event.tenant_id,
                            {"event_id": str(event.id), **event.payload},
                            timeout=30,
                        )
                    else:
                        job = db.get(Job, event.aggregate_id)
                        if (
                            job is None
                            or job.tenant_id != event.tenant_id
                            or event.payload.get("job_id") != str(job.id)
                            or event.payload.get("kind") != job.kind
                        ):
                            raise ValueError("OUTBOX_JOB_MISMATCH")
                        if db.get(JobDelivery, job.id) is None:
                            db.add(
                                JobDelivery(
                                    job_id=job.id, event_id=event.id, tenant_id=event.tenant_id
                                )
                            )
                    event.status = "published"
                    event.published_at = datetime.now(UTC)
                    event.last_error = None
                    db.flush()
                published += 1
            except Exception as exc:
                event.last_error = type(exc).__name__
        db.commit()
    return published

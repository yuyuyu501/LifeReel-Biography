from uuid import uuid4

from sqlalchemy import select

from lifereel_api.architecture.events import EventEnvelope, event_type_for_job
from lifereel_api.architecture.services import SERVICE_CATALOG
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.identity.models import Tenant
from lifereel_api.modules.jobs.events import OutboxEvent
from lifereel_api.modules.jobs.service import create_job


def test_service_catalog_covers_business_and_runtime_boundaries():
    required = {
        "identity", "model_gateway", "interview", "memory", "script", "media",
        "billing", "worker",
    }
    assert required <= set(SERVICE_CATALOG)
    assert SERVICE_CATALOG["interview"]["runtime"] == "api + worker-interview"
    assert SERVICE_CATALOG["media"]["runtime"] == "api + worker-media"
    assert SERVICE_CATALOG["storage"]["runtime"] == "external OSS/S3"


def test_job_events_are_versioned_and_stable():
    tenant_id = uuid4()
    job_id = uuid4()
    event = EventEnvelope(
        event_type=event_type_for_job("production.render"),
        tenant_id=tenant_id,
        aggregate_id=job_id,
        payload={"job_id": str(job_id)},
    )
    assert event.event_type == "media.production.queued"
    assert event.schema_version == 1
    assert event.tenant_id == tenant_id
    assert event.model_dump()["aggregate_id"] == job_id


def test_job_creation_writes_transactional_outbox_event():
    tenant_id = uuid4()
    idempotency_key = f"architecture-test-{tenant_id}"

    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="Architecture test", slug=str(tenant_id)))
        job, created = create_job(
            db,
            tenant_id,
            "interview.turn.process",
            {"session_id": str(uuid4())},
            idempotency_key,
        )
        db.commit()

        event = db.scalar(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == job.id)
        )
        assert created is True
        assert event is not None
        assert event.event_type == "interview.turn.queued"
        assert event.status == "pending"
        assert event.payload["job_id"] == str(job.id)

        duplicate, duplicate_created = create_job(
            db,
            tenant_id,
            "interview.turn.process",
            {"session_id": str(uuid4())},
            idempotency_key,
        )
        assert duplicate.id == job.id
        assert duplicate_created is False
        assert db.scalar(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == job.id)
        ).id == event.id

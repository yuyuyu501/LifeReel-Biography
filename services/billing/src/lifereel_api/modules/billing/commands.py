"""Billing messages committed with the owning business result."""

from datetime import UTC, datetime
from uuid import uuid4, uuid5

from sqlalchemy import select

from lifereel_api.modules.billing.models import Charge
from lifereel_api.modules.jobs.events import OutboxEvent


def enqueue_transition(db, tenant_id, key, settle, result_project_id=None):
    charge = db.scalar(
        select(Charge).where(Charge.tenant_id == tenant_id, Charge.business_key == key)
        .execution_options(populate_existing=True)
    )
    if charge is None:
        return
    event_id = uuid5(tenant_id, f"billing.transition:{key}:{charge.attempt}:{settle}")
    if db.get(OutboxEvent, event_id):
        return
    db.add(
        OutboxEvent(
            id=event_id,
            tenant_id=tenant_id,
            event_type="billing.transition.requested",
            aggregate_id=charge.id,
            idempotency_key=str(event_id),
            payload={
                "operation": "transition",
                "key": key,
                "settle": settle,
                "attempt": charge.attempt,
                "result_project_id": result_project_id,
            },
            status="pending",
            occurred_at=datetime.now(UTC),
        )
    )


def enqueue_usage(tenant_id, payload):
    from lifereel_api.core.database import SessionLocal

    request_id = payload.get("request_id")
    identity = (
        f"usage:{payload['operation']}:{payload['model']}:{request_id}:{payload['status']}"
        if request_id
        else None
    )
    event_id = uuid5(tenant_id, identity) if identity else uuid4()
    with SessionLocal() as db:
        if db.get(OutboxEvent, event_id) is None:
            db.add(
                OutboxEvent(
                    id=event_id,
                    tenant_id=tenant_id,
                    event_type="billing.usage.recorded",
                    aggregate_id=event_id,
                    idempotency_key=str(event_id),
                    payload={"operation": "usage", "receipt": payload},
                )
            )
            db.commit()

from types import SimpleNamespace
from uuid import UUID, uuid5

from sqlalchemy import select

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing import service, tokens, usage
from lifereel_api.modules.billing.models import BillingCommand, Charge, UsageEvent

BUSINESS = {
    "identity",
    "interview",
    "worker-interview",
    "script",
    "media",
    "worker-media",
    "tasks",
    "model-gateway",
    "memory",
}


def wallet(db, tenant, data):
    row = service.lock_wallet(db, tenant)
    return {
        key: getattr(row, key)
        for key in (
            "paid_cents",
            "bonus_cents",
            "frozen_paid_cents",
            "frozen_bonus_cents",
            "token_remainder_nano",
        )
    }


def reserve(db, tenant, data):
    from lifereel_api.modules.jobs.events import OutboxEvent

    service.lock_wallet(db, tenant)
    hold = db.scalar(
        select(Charge).where(Charge.tenant_id == tenant, Charge.business_key == data["key"])
    )
    if hold:
        # Resolve prior committed completion/release before a new attempt.
        pending = list(
            db.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.tenant_id == tenant,
                    OutboxEvent.aggregate_id == hold.id,
                    OutboxEvent.event_type == "billing.transition.requested",
                    OutboxEvent.status == "pending",
                )
                .order_by(OutboxEvent.occurred_at, OutboxEvent.id)
            )
        )
        for event in pending:
            command(db, tenant, {"event_id": str(event.id), **event.payload})
    row = service.reserve(
        db,
        tenant,
        data["key"],
        data["amount"],
        data["kind"],
        data["title"],
        data["price"],
        allow_overdraft=data.get("allow_overdraft", False),
    )
    return {
        "id": str(row.id),
        "price_snapshot": row.price_snapshot,
        "status": row.status,
        "attempt": row.attempt,
        "amount_cents": row.amount_cents,
    }


def begin_tokens(db, tenant, data):
    context = usage.current_context()
    if not context or context[0] != tenant:
        raise ApiError(403, ErrorCode.AUTH_MEMBERSHIP_MISSING)
    return {"reservation": tokens.begin(data["base_url"], data["model"], context)}


def video_finish(db, tenant, data):
    run = SimpleNamespace(
        id=UUID(data["run_id"]), tenant_id=tenant, output_manifest=data["manifest"]
    )
    service.lock_wallet(db, tenant)
    hold = db.scalar(
        select(Charge).where(Charge.tenant_id == tenant, Charge.business_key == f"video:{run.id}")
    )
    if hold is None:
        return {"billing": run.output_manifest.get("billing")}
    key = uuid5(tenant, f"video.finish:{run.id}:{hold.attempt}")
    previous = db.get(BillingCommand, key)
    if previous:
        return previous.result
    service.video_finish(db, run, bool(data["success"]))
    result = {"billing": run.output_manifest.get("billing")}
    if not result["billing"] or result["billing"].get("status") != "pending":
        db.add(BillingCommand(id=key, tenant_id=tenant, result=result))
    return result


def command(db, tenant, data):
    event_id = UUID(data["event_id"])
    service.lock_wallet(db, tenant)
    previous = db.get(BillingCommand, event_id)
    if previous:
        if previous.tenant_id != tenant:
            raise ApiError(403, ErrorCode.AUTH_MEMBERSHIP_MISSING)
        return previous.result
    if data["operation"] == "transition":
        charge = db.scalar(
            select(Charge).where(Charge.tenant_id == tenant, Charge.business_key == data["key"])
        )
        if charge and charge.attempt == data["attempt"]:
            if not data["settle"]:
                from lifereel_api.modules.jobs.events import OutboxEvent

                outcomes = db.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.tenant_id == tenant,
                        OutboxEvent.aggregate_id == charge.id,
                        OutboxEvent.event_type == "billing.transition.requested",
                    )
                )
                if any(
                    e.payload.get("settle") and e.payload.get("attempt") == charge.attempt
                    for e in outcomes
                ):
                    db.add(BillingCommand(id=event_id, tenant_id=tenant, result={"accepted": True}))
                    db.flush()
                    return {"accepted": True}
            project_id = data.get("result_project_id")
            if project_id:
                from lifereel_api.modules.script.models import ScriptProject

                project = db.scalar(
                    select(ScriptProject).where(
                        ScriptProject.id == UUID(project_id),
                        ScriptProject.tenant_id == tenant,
                    )
                )
                if project is None:
                    raise ApiError(409, ErrorCode.BILLING_STATE_INVALID)
                charge.price_snapshot = {**charge.price_snapshot, "result_project_id": project_id}
            service.transition(db, tenant, data["key"], bool(data["settle"]))
    elif data["operation"] == "usage":
        db.commit()
        receipt = dict(data["receipt"])
        operation, reference = receipt.pop("operation"), receipt.pop("reference")
        token = usage._context.set((tenant, operation, reference))
        try:
            usage.record(**receipt, receipt_id=event_id)
        finally:
            usage._context.reset(token)
        if db.get(UsageEvent, event_id) is None:
            duplicate = (
                db.scalar(
                    select(UsageEvent).where(
                        UsageEvent.tenant_id == tenant,
                        UsageEvent.operation == operation,
                        UsageEvent.provider_request_id == receipt.get("request_id"),
                        UsageEvent.status == receipt["status"],
                    )
                )
                if receipt.get("request_id")
                else None
            )
            if duplicate is None:
                raise RuntimeError("BILLING_RECEIPT_NOT_DURABLE")
        service.lock_wallet(db, tenant)
        if db.get(BillingCommand, event_id):
            return {"accepted": True}
    else:
        raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)
    db.add(BillingCommand(id=event_id, tenant_id=tenant, result={"accepted": True}))
    db.flush()
    return {"accepted": True}


OPERATIONS = {
    "billing.wallet": (BUSINESS, wallet),
    "billing.reserve": (BUSINESS, reserve),
    "billing.tokens-begin": ({"model-gateway"}, begin_tokens),
    "billing.video-finish": ({"media", "worker-media", "tasks"}, video_finish),
    "billing.command": ({"tasks"}, command),
}

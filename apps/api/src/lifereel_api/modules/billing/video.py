"""Settle one video budget from durable provider receipts, never from clip length."""

from uuid import UUID

from sqlalchemy import select

from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing import service, tokens
from lifereel_api.modules.billing.models import Charge, UsageEvent

MODEL = "doubao-seedance-2-0-mini-260615"
VERSION = "ark-seedance-mini-720p-2026-09-x1.5"
SOURCE = "https://docs.volcengine.com/docs/82379/1544106?lang=zh"


def validate_config(config: dict) -> None:
    if (
        config.get("model") != MODEL or config.get("resolution") != "720p"
        or config.get("mode") != "segmented"
    ):
        raise ApiError(503, ErrorCode.BILLING_MODEL_UNPRICED)


def quote(model: str, usage: dict, status: str) -> dict:
    if model == tokens.MODEL:
        return tokens.quote(model, usage)
    if model != MODEL or not isinstance(usage, dict):
        raise ValueError("unpriced_model_or_usage")
    # Officially failed video tasks are not billed. Successful tasks require a receipt.
    if status == "failed" and not usage:
        count = 0
    else:
        count = usage.get("completion_tokens")
        if type(count) is not int or count < 0:
            raise ValueError("missing_completion_tokens")
    cost = count * 23_000
    return {
        "version": VERSION, "source": SOURCE, "completion_tokens": count,
        "official_cost_nano": cost, "retail_nano": cost * 3 // 2,
        "markup": "1.5", "output_cny_per_million": "23",
    }


def use_reserved_budget(tenant_id: UUID, reference: str) -> bool:
    with SessionLocal() as db:
        service.lock_wallet(db, tenant_id)
        hold = db.scalar(select(Charge).where(
            Charge.tenant_id == tenant_id, Charge.business_key == f"video:{reference}",
        ))
        if hold is None or hold.kind != "video_hold":
            return False
        if hold.status != "reserved":
            raise ApiError(409, ErrorCode.BILLING_STATE_INVALID)
        return True


def settle_run(db, run, success: bool) -> None:
    wallet = service.lock_wallet(db, run.tenant_id)
    key = f"video:{run.id}"
    hold = db.scalar(select(Charge).where(
        Charge.tenant_id == run.tenant_id, Charge.business_key == key,
    ))
    if hold is None or hold.status != "reserved":
        return
    manifest = dict(run.output_manifest or {})
    events = list(db.scalars(select(UsageEvent).where(
        UsageEvent.tenant_id == run.tenant_id, UsageEvent.operation == "video",
        UsageEvent.reference == str(run.id),
    ).order_by(UsageEvent.created_at, UsageEvent.id)))
    terminal_ids = {
        e.provider_request_id for e in events
        if e.model == MODEL and e.status in {"succeeded", "failed"} and e.provider_request_id
    }
    expected_ids = {
        e.provider_request_id for e in events
        if e.model == MODEL and e.status == "submitted" and e.provider_request_id
    }
    segments = manifest.get("segments") or []
    for segment in segments:
        if segment.get("task_id"):
            expected_ids.add(segment["task_id"])
        expected_ids.update(segment.get("previous_task_ids") or [])
    pending = bool(expected_ids - terminal_ids) or any(
        s.get("status") in {"submitting", "submission_unknown"} and not s.get("task_id")
        for s in segments
    )
    if success and not any(e.model == MODEL and e.status == "succeeded" for e in events):
        pending = True
    priced = []
    receipt_keys = set()
    for event in events:
        if event.status == "submitted" or event.metering.get("status") in {
            "settled", "duplicate", "released",
        }:
            continue
        receipt = (event.model, event.provider_request_id) if event.provider_request_id else None
        if receipt:
            previous = db.scalars(select(UsageEvent).where(
                UsageEvent.tenant_id == run.tenant_id, UsageEvent.model == event.model,
                UsageEvent.provider_request_id == event.provider_request_id,
                UsageEvent.id != event.id,
            ))
            if receipt in receipt_keys or any(
                e.metering.get("status") == "settled" for e in previous
            ):
                event.metering = {"status": "duplicate"}
                continue
            receipt_keys.add(receipt)
        try:
            price = quote(event.model, event.usage, event.status)
        except ValueError as exc:
            pending = True
            event.metering = {"status": "pending", "reason": str(exc)}
        else:
            priced.append((event, price))
    if pending:
        hold.price_snapshot = {**hold.price_snapshot, "pending": True}
        run.output_manifest = {**manifest, "billing": {
            **manifest.get("billing", {}), "status": "pending",
            "reserved_cents": hold.amount_cents,
        }}
        return
    total_nano = sum(price["retail_nano"] for _, price in priced)
    cents, remainder = divmod(wallet.token_remainder_nano + total_nano, tokens.NANO_PER_CENT)
    service.transition(db, run.tenant_id, key, False)
    service.debit_actual(
        db, run.tenant_id, f"video-usage:{run.id}:{hold.attempt}", cents,
        f"{hold.title} · 影像实际用量",
        {"version": VERSION, "retail_nano": total_nano, "reserved_cents": hold.amount_cents},
    )
    wallet.token_remainder_nano = remainder
    for event, price in priced:
        event.metering = {**event.metering, **price, "status": "settled", "reservation": key}
    previous = manifest.get("billing") or {}
    charged = previous.get("charged_cents", 0) + cents
    run.output_manifest = {**manifest, "billing": {
        "status": "settled", "reserved_cents": hold.amount_cents,
        "charged_cents": charged,
        "retail_nano": previous.get("retail_nano", 0) + total_nano,
        "last_settled_cents": cents,
        "returned_cents": max(0, hold.amount_cents - cents),
        "additional_cents": max(0, cents - hold.amount_cents),
    }}

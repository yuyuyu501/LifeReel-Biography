"""Operator-only token reconciliation. Never expose this as a customer API."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from lifereel_api import main as _main  # noqa: F401 - register all database models
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.billing import service, tokens
from lifereel_api.modules.billing.models import Charge, UsageEvent


def reconcile(db, hold_id: UUID, operator: str, reference: str, receipt: dict | None):
    hold = db.get(Charge, hold_id)
    if hold is None or hold.kind != "token_hold":
        raise ValueError("token_hold_not_found")
    service.lock_wallet(db, hold.tenant_id)
    db.refresh(hold)
    if hold.status != "reserved":
        raise ValueError("token_hold_already_resolved")
    if not hold.price_snapshot.get("pending") and (
        hold.created_at.replace(tzinfo=UTC) > datetime.now(UTC) - timedelta(minutes=5)
    ):
        raise ValueError("token_hold_still_in_flight")
    if hold.price_snapshot.get("version") != tokens.VERSION:
        raise ValueError("tariff_version_mismatch")
    audit = {"operator": operator, "reference": reference, "at": datetime.now(UTC).isoformat()}
    events = list(db.scalars(select(UsageEvent).where(UsageEvent.tenant_id == hold.tenant_id)))
    event = next(
        (row for row in events if row.metering.get("reservation") == hold.business_key), None
    )
    if receipt is None:
        if event and event.usage:
            raise ValueError("receipt_exists_settle_instead")
        service.transition(db, hold.tenant_id, hold.business_key, False)
        if event:
            event.metering = {**event.metering, "status": "released", "reconciliation": audit}
    else:
        usage, request_id = receipt.get("usage"), receipt.get("id")
        tokens.quote(tokens.MODEL, usage)
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 200:
            raise ValueError("provider_request_id_required")
        if event and event.provider_request_id and event.provider_request_id != request_id:
            raise ValueError("provider_request_id_mismatch")
        if event is None:
            event = UsageEvent(
                tenant_id=hold.tenant_id,
                operation=hold.price_snapshot["operation"],
                reference=hold.price_snapshot.get("reference"),
                model=tokens.MODEL,
                status="reconciled",
                usage={},
                duration_ms=0,
            )
            db.add(event)
        original = event.usage
        event.usage = usage
        event.provider_request_id = request_id
        db.flush()
        tokens.settle(db, event, hold.business_key)
        event.metering = {**event.metering, "original_usage": original, "reconciliation": audit}
    hold.price_snapshot = {**hold.price_snapshot, "reconciliation": audit, "pending": False}
    db.flush()
    return {
        "hold_id": str(hold.id),
        "status": hold.status,
        "metering": event.metering if event else {"status": "released"},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("list", help="List unresolved token holds, including orphan reservations")
    for name in ("settle", "release"):
        command = commands.add_parser(name)
        command.add_argument("--hold-id", type=UUID, required=True)
        command.add_argument("--operator", required=True)
        command.add_argument("--reference", required=True, help="Provider reconciliation evidence")
        if name == "settle":
            command.add_argument(
                "--receipt",
                type=Path,
                required=True,
                help="Verified provider JSON containing id and usage",
            )
        else:
            command.add_argument("--confirmed-no-charge", action="store_true", required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.action == "list":
            holds = db.scalars(
                select(Charge)
                .where(
                    Charge.kind == "token_hold",
                    Charge.status == "reserved",
                )
                .order_by(Charge.created_at)
            )
            print(
                json.dumps(
                    [
                        {
                            "hold_id": str(row.id),
                            "tenant_id": str(row.tenant_id),
                            "created_at": row.created_at,
                            "amount_cents": row.amount_cents,
                            "context": row.price_snapshot,
                        }
                        for row in holds
                    ],
                    default=str,
                )
            )
            return
        if (
            not 1 <= len(args.operator.strip()) <= 100
            or not 1 <= len(args.reference.strip()) <= 300
        ):
            parser.error("operator/reference required, max 100/300 characters")
        try:
            receipt = (
                json.loads(args.receipt.read_text(encoding="utf-8-sig"))
                if args.action == "settle"
                else None
            )
            if args.action == "settle" and not isinstance(receipt, dict):
                raise ValueError("receipt_object_required")
            result = reconcile(
                db, args.hold_id, args.operator.strip(), args.reference.strip(), receipt
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            parser.exit(1, f"Reconciliation failed: {type(exc).__name__}\n")
        print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()

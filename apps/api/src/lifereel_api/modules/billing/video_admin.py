"""Operator-only correction of incomplete video receipts; no customer write endpoint."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from lifereel_api import main as _main  # noqa: F401
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.billing import service, video
from lifereel_api.modules.billing.models import UsageEvent
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.modules.production.models import ProductionRun


def reconcile(db, run_id, event_id, receipt, operator, reference):
    with execution_lock(db, run_id) as acquired:
        if not acquired:
            raise ValueError("production_still_running")
        run = db.get(ProductionRun, run_id)
        if run is None or run.status not in {"completed", "failed"}:
            raise ValueError("production_not_terminal")
        service.lock_wallet(db, run.tenant_id)
        event = db.get(UsageEvent, event_id)
        if (
            event is None or event.tenant_id != run.tenant_id or event.reference != str(run.id)
            or event.operation != "video" or event.status == "submitted"
            or event.metering.get("status") in {"settled", "released", "duplicate"}
            or (run.output_manifest or {}).get("billing", {}).get("status") != "pending"
        ):
            raise ValueError("receipt_not_pending_for_run")
        if (
            not isinstance(receipt, dict) or not isinstance(receipt.get("id"), str)
            or not 1 <= len(receipt["id"]) <= 200
            or event.provider_request_id not in {None, receipt["id"]}
            or not operator.strip() or not reference.strip()
        ):
            raise ValueError("receipt_identity_or_audit_invalid")
        video.quote(event.model, receipt.get("usage"), event.status)
        event.metering = {
            **event.metering, "original_usage": event.usage,
            "reconciliation": {"operator": operator[:100], "reference": reference[:300],
                               "at": datetime.now(UTC).isoformat()},
        }
        event.usage = receipt["usage"]
        event.provider_request_id = receipt["id"]
        db.flush()
        video.settle_run(db, run, run.status == "completed")
        db.commit()
        return run.output_manifest["billing"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=UUID, required=True)
    parser.add_argument("--event-id", type=UUID, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reference", required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        result = reconcile(
            db, args.run_id, args.event_id,
            json.loads(args.receipt.read_text(encoding="utf-8-sig")),
            args.operator, args.reference,
        )
        print(json.dumps(result))


if __name__ == "__main__":
    main()

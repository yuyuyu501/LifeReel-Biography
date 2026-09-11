from __future__ import annotations

import logging
from contextvars import ContextVar
from functools import wraps
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.billing.models import Charge, UsageEvent

_context: ContextVar[tuple | None] = ContextVar("provider_usage", default=None)
logger = logging.getLogger(__name__)


def track_usage(operation: str):
    def decorate(function):
        @wraps(function)
        def wrapped(db, tenant_id, *args, **kwargs):
            reference = str(args[0]) if args and isinstance(args[0], UUID) else None
            if reference is None and args:
                request_id = getattr(args[0], "idempotency_key", None)
                if request_id is not None:
                    reference = str(request_id)[:100]
            parent = _context.get()
            if parent and parent[0] == tenant_id and parent[2]:
                reference = parent[2]
            token = _context.set((tenant_id, operation, reference))
            try:
                return function(db, tenant_id, *args, **kwargs)
            finally:
                _context.reset(token)

        return wrapped

    return decorate


def current_context() -> tuple | None:
    return _context.get()


def record(
    model: str,
    status: str,
    usage: dict,
    duration_ms: int,
    request_id: str | None = None,
    error: str | None = None,
    reservation: str | None = None,
    rejected: bool = False,
) -> None:
    context = _context.get()
    if context is None:
        return
    tenant_id, operation, reference = context
    try:
        # Independent transaction retains provider usage even when business work rolls back.
        with SessionLocal() as db:
            if reservation:
                from lifereel_api.modules.billing.service import lock_wallet

                # Lock before inserting a tenant FK to avoid concurrent lock upgrades.
                lock_wallet(db, tenant_id)
            event = UsageEvent(
                tenant_id=tenant_id,
                operation=operation,
                reference=reference,
                model=model[:150],
                status=status,
                usage=usage,
                duration_ms=max(0, duration_ms),
                provider_request_id=request_id[:200] if request_id else None,
                error_code=error[:80] if error else None,
            )
            db.add(event)
            db.flush()
            if reservation:
                from lifereel_api.modules.billing.service import transition
                from lifereel_api.modules.billing.tokens import settle

                try:
                    # A settlement failure must not discard the original receipt.
                    with db.begin_nested():
                        if rejected and not usage:
                            transition(db, tenant_id, reservation, False)
                            event.metering = {
                                "status": "released",
                                "reason": "request_rejected",
                                "reservation": reservation,
                            }
                        else:
                            settle(db, event, reservation)
                except Exception:
                    logger.exception(
                        "Token settlement failed; retaining receipt for reconciliation"
                    )
                    event.metering = {
                        "status": "pending",
                        "reason": "settlement_failed",
                        "reservation": reservation,
                    }
                    hold = db.scalar(
                        select(Charge).where(
                            Charge.tenant_id == tenant_id,
                            Charge.business_key == reservation,
                        )
                    )
                    if hold:
                        hold.price_snapshot = {**hold.price_snapshot, "pending": True}
            db.commit()
    except IntegrityError:
        # Re-fetching a completed cloud task is not a second model invocation.
        try:
            with SessionLocal() as db:
                duplicate = request_id and db.scalar(
                    select(UsageEvent.id).where(
                        UsageEvent.tenant_id == tenant_id,
                        UsageEvent.operation == operation,
                        UsageEvent.model == model[:150],
                        UsageEvent.provider_request_id == request_id[:200],
                        UsageEvent.status == status,
                    )
                )
            if not duplicate:
                logger.exception(
                    "Provider usage integrity failure; billing reconciliation required"
                )
            elif reservation:
                from lifereel_api.modules.billing.service import transition

                with SessionLocal() as db:
                    transition(db, tenant_id, reservation, False)
                    db.commit()
        except Exception:
            logger.exception("Provider usage verification failed; billing reconciliation required")
    except Exception:
        logger.exception("Provider usage persistence failed; billing reconciliation required")

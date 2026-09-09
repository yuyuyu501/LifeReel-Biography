from __future__ import annotations

import logging
from contextvars import ContextVar
from functools import wraps
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.billing.models import UsageEvent

_context: ContextVar[tuple | None] = ContextVar("provider_usage", default=None)
logger = logging.getLogger(__name__)


def track_usage(operation: str):
    def decorate(function):
        @wraps(function)
        def wrapped(db, tenant_id, *args, **kwargs):
            reference = str(args[0]) if args and isinstance(args[0], UUID) else None
            token = _context.set((tenant_id, operation, reference))
            try:
                return function(db, tenant_id, *args, **kwargs)
            finally:
                _context.reset(token)

        return wrapped

    return decorate


def record(
    model: str,
    status: str,
    usage: dict,
    duration_ms: int,
    request_id: str | None = None,
    error: str | None = None,
) -> None:
    context = _context.get()
    if context is None:
        return
    tenant_id, operation, reference = context
    try:
        # Independent transaction retains provider usage even when business work rolls back.
        with SessionLocal() as db:
            db.add(
                UsageEvent(
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
            )
            db.commit()
    except IntegrityError:
        # Re-fetching a completed cloud task is not a second model invocation.
        try:
            with SessionLocal() as db:
                duplicate = request_id and db.scalar(
                    select(UsageEvent.id).where(
                        UsageEvent.tenant_id == tenant_id,
                        UsageEvent.operation == operation,
                        UsageEvent.provider_request_id == request_id[:200],
                        UsageEvent.status == status,
                    )
                )
            if not duplicate:
                logger.exception(
                    "Provider usage integrity failure; billing reconciliation required"
                )
        except Exception:
            logger.exception("Provider usage verification failed; billing reconciliation required")
    except Exception:
        logger.exception("Provider usage persistence failed; billing reconciliation required")

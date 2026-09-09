from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.billing import service
from lifereel_api.modules.billing.models import LedgerEntry, UsageEvent

router = APIRouter(prefix="/wallet", tags=["wallet"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]


@router.get("")
def wallet(db: Db, tenant_id: Tenant):
    row = service.lock_wallet(db, tenant_id)
    result = {
        "paid_cents": row.paid_cents,
        "bonus_cents": row.bonus_cents,
        "frozen_cents": row.frozen_paid_cents + row.frozen_bonus_cents,
        "available_cents": service.available(row),
        "prices": service.prices(),
    }
    db.commit()
    return result


@router.get("/ledger")
def ledger(
    db: Db,
    tenant_id: Tenant,
    page: int = Query(1, ge=1),
    event: str | None = Query(None, pattern="^(bonus|reserve|consume|release)$"),
):
    statement = select(LedgerEntry).where(LedgerEntry.tenant_id == tenant_id)
    if event:
        statement = statement.where(LedgerEntry.event == event)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = db.scalars(
        statement.order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
        .offset((page - 1) * 20)
        .limit(20)
    )
    return {
        "total": total,
        "page": page,
        "page_size": 20,
        "items": [
            {
                "id": str(row.id),
                "charge_id": str(row.charge_id) if row.charge_id else None,
                "event": row.event,
                "title": row.title,
                "amount_cents": row.amount_cents,
                "available_after_cents": row.available_after_cents,
                "paid_delta": row.paid_delta,
                "bonus_delta": row.bonus_delta,
                "frozen_delta": row.frozen_delta,
                "created_at": row.created_at,
            }
            for row in rows
        ],
    }


@router.get("/usage")
def usage(db: Db, tenant_id: Tenant, page: int = Query(1, ge=1)):
    query = select(UsageEvent).where(UsageEvent.tenant_id == tenant_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    return {
        "total": total,
        "page": page,
        "page_size": 20,
        "items": [
            {
                "id": str(row.id),
                "operation": row.operation,
                "reference": row.reference,
                "model": row.model,
                "status": row.status,
                "usage": row.usage,
                "duration_ms": row.duration_ms,
                "provider_request_id": row.provider_request_id,
                "created_at": row.created_at,
                "error_code": row.error_code,
            }
            for row in db.scalars(
                query.order_by(UsageEvent.created_at.desc(), UsageEvent.id.desc())
                .offset((page - 1) * 20)
                .limit(20)
            )
        ],
    }


@router.post("/recharge")
def recharge(tenant_id: Tenant):
    # No client-provided amount or fake confirmation may credit real balances.
    raise ApiError(503, ErrorCode.PAYMENT_NOT_ENABLED)

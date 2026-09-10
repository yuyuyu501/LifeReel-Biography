from datetime import timedelta
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.models import utcnow
from lifereel_api.modules.billing import service
from lifereel_api.modules.billing.models import LedgerEntry, RechargeOrder


class CreateRecharge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    amount_cents: int = Field(strict=True, ge=1, le=20000)


class PaymentReport(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    payer_reference: str = Field(pattern=r"^[A-Za-z0-9_-]{6,64}$")


def enabled() -> bool:
    settings = get_settings()
    return settings.manual_wechat_enabled and Path(settings.manual_wechat_qr_path).is_file()


def require_enabled() -> None:
    if not enabled():
        raise ApiError(503, ErrorCode.PAYMENT_NOT_ENABLED)


def serialize(order: RechargeOrder) -> dict:
    return {
        key: getattr(order, key)
        for key in (
            "id",
            "amount_cents",
            "status",
            "payer_reference",
            "review_note",
            "created_at",
            "reviewed_at",
        )
    }


def get_order(db: Session, tenant_id: UUID, order_id: UUID) -> RechargeOrder:
    row = db.scalar(
        select(RechargeOrder)
        .where(
            RechargeOrder.tenant_id == tenant_id,
            RechargeOrder.id == order_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise ApiError(404, ErrorCode.RECHARGE_NOT_FOUND)
    return row


def create(db: Session, tenant_id: UUID, payload: CreateRecharge) -> RechargeOrder:
    require_enabled()
    service.lock_wallet(db, tenant_id)
    existing = db.scalar(
        select(RechargeOrder).where(
            RechargeOrder.tenant_id == tenant_id,
            RechargeOrder.request_id == payload.request_id,
        )
    )
    if existing:
        if existing.amount_cents != payload.amount_cents:
            raise ApiError(409, ErrorCode.RECHARGE_REQUEST_CONFLICT)
        return existing
    query = (
        select(func.count()).select_from(RechargeOrder).where(RechargeOrder.tenant_id == tenant_id)
    )
    recent_count = db.scalar(query.where(RechargeOrder.created_at >= utcnow() - timedelta(hours=1)))
    if recent_count >= 10:
        raise ApiError(429, ErrorCode.RECHARGE_LIMIT_REACHED)
    row = RechargeOrder(
        tenant_id=tenant_id, request_id=payload.request_id, amount_cents=payload.amount_cents
    )
    db.add(row)
    db.flush()
    return row


def report(db: Session, tenant_id: UUID, order_id: UUID, payload: PaymentReport) -> RechargeOrder:
    # Keep accepting reports when new payments are disabled: money may already have been sent.
    service.lock_wallet(db, tenant_id)
    row = get_order(db, tenant_id, order_id)
    if row.status == "submitted" and row.payer_reference == payload.payer_reference:
        return row
    if row.status != "pending":
        raise ApiError(409, ErrorCode.RECHARGE_STATE_INVALID)
    row.payer_reference = payload.payer_reference
    row.status = "submitted"
    db.flush()
    return row


def cancel(db: Session, tenant_id: UUID, order_id: UUID) -> RechargeOrder:
    service.lock_wallet(db, tenant_id)
    row = get_order(db, tenant_id, order_id)
    if row.status == "cancelled":
        return row
    if row.status != "pending":
        raise ApiError(409, ErrorCode.RECHARGE_STATE_INVALID)
    row.status = "cancelled"
    db.flush()
    return row


def review(
    db: Session,
    order_id: UUID,
    operator: str,
    reference: str | None,
    amount_cents: int | None,
    rejection: str | None = None,
) -> RechargeOrder:
    """Server CLI only. A family owner is NOT a payment administrator."""
    operator = operator.strip()
    if not 1 <= len(operator) <= 100:
        raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)
    if rejection is not None:
        rejection = rejection.strip()
        if not 1 <= len(rejection) <= 300:
            raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)
    else:
        if type(amount_cents) is not int or not 1 <= amount_cents <= 20000:
            raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)
        try:
            reference = PaymentReport(payer_reference=reference).payer_reference
        except ValidationError as exc:
            raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED) from exc
    tenant_id = db.scalar(select(RechargeOrder.tenant_id).where(RechargeOrder.id == order_id))
    if tenant_id is None:
        raise ApiError(404, ErrorCode.RECHARGE_NOT_FOUND)
    wallet = service.lock_wallet(db, tenant_id)
    row = get_order(db, tenant_id, order_id)
    if (
        not rejection
        and row.status == "credited"
        and row.verified_reference == reference
        and row.amount_cents == amount_cents
    ):
        return row
    if row.status not in {"pending", "submitted"}:
        raise ApiError(409, ErrorCode.RECHARGE_STATE_INVALID)
    if rejection:
        row.status = "rejected"
        row.review_note = rejection
    else:
        if row.amount_cents != amount_cents:
            raise ApiError(409, ErrorCode.RECHARGE_AMOUNT_MISMATCH)
        if not reference:
            raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)
        row.verified_reference = reference
        row.status = "credited"
        wallet.paid_cents += row.amount_cents
        db.add(
            LedgerEntry(
                tenant_id=tenant_id,
                event_key=f"recharge:{row.id}",
                event="recharge",
                title="微信充值（人工核实）",
                amount_cents=row.amount_cents,
                paid_delta=row.amount_cents,
                available_after_cents=service.available(wallet),
            )
        )
    row.reviewed_by = operator
    row.reviewed_at = utcnow()
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, ErrorCode.RECHARGE_RECEIPT_USED) from exc
    return row

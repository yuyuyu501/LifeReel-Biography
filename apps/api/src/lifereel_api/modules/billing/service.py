from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing.models import Charge, LedgerEntry, Wallet
from lifereel_api.modules.identity.models import Tenant


def prices() -> dict:
    settings = get_settings()
    token_mode = settings.billing_text_mode == "tokens"
    return {
        "version": settings.billing_price_version,
        "video_cents_per_second": settings.billing_video_cents_per_second,
        "video_billing_mode": settings.billing_video_mode,
        "video_reserve_cents": settings.billing_video_reserve_cents,
        "video_cny_per_million": "34.5",
        "video_reference_cny_per_million": "21",
        "video_markup": "1.5",
        "script_chapter_cents": settings.billing_script_chapter_cents,
        "welcome_bonus_cents": settings.billing_welcome_bonus_cents,
        "payment_enabled": False,
        "script_billing_mode": settings.billing_text_mode,
        "text_markup": "1.5" if token_mode else None,
    }


def script_update_price() -> int:
    settings = get_settings()
    return 0 if settings.billing_text_mode == "tokens" else settings.billing_script_chapter_cents


def available(wallet: Wallet) -> int:
    return (
        wallet.paid_cents
        + wallet.bonus_cents
        - wallet.frozen_paid_cents
        - wallet.frozen_bonus_cents
    )


def read_wallet(db: Session, tenant_id: UUID) -> Wallet:
    """Read a current balance without serializing against billing writers.

    Only first access needs the existing locked, durable welcome-grant flow.
    Charging and settlement must continue to use lock_wallet directly.
    """
    wallet = db.scalar(
        select(Wallet)
        .where(Wallet.tenant_id == tenant_id)
        .execution_options(populate_existing=True)
    )
    if wallet is None:
        wallet = lock_wallet(db, tenant_id)
        db.commit()
    return wallet


def lock_wallet(db: Session, tenant_id: UUID) -> Wallet:
    # Lock the existing parent even on first access, avoiding competing welcome grants.
    # NO KEY UPDATE serializes balances without blocking FK inserts in the business
    # transaction while provider receipts are settled in an independent transaction.
    if db.scalar(
        select(Tenant.id).where(Tenant.id == tenant_id).with_for_update(key_share=True)
    ) is None:
        raise ApiError(404, ErrorCode.WALLET_NOT_FOUND)
    wallet = db.scalar(
        select(Wallet)
        .where(Wallet.tenant_id == tenant_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if wallet is None:
        wallet = Wallet(
            tenant_id=tenant_id,
            paid_cents=0,
            bonus_cents=get_settings().billing_welcome_bonus_cents,
            frozen_paid_cents=0,
            frozen_bonus_cents=0,
        )
        db.add(wallet)
        db.flush()
        db.add(
            LedgerEntry(
                tenant_id=tenant_id,
                event_key="welcome:v1",
                event="bonus",
                title="新用户体验额度",
                amount_cents=wallet.bonus_cents,
                bonus_delta=wallet.bonus_cents,
                available_after_cents=available(wallet),
            )
        )
        db.flush()
    return wallet


def _event(
    db: Session,
    wallet: Wallet,
    charge: Charge,
    event: str,
    paid: int = 0,
    bonus: int = 0,
    frozen: int = 0,
) -> None:
    if charge.amount_cents == 0:
        return
    db.add(
        LedgerEntry(
            tenant_id=wallet.tenant_id,
            charge_id=charge.id,
            event_key=f"{charge.id}:{charge.attempt}:{event}",
            event=event,
            title=charge.title,
            amount_cents=charge.amount_cents,
            paid_delta=paid,
            bonus_delta=bonus,
            frozen_delta=frozen,
            available_after_cents=available(wallet),
        )
    )
    db.flush()


def reserve(
    db: Session, tenant_id: UUID, key: str, amount: int, kind: str, title: str, price: dict,
    *, allow_overdraft: bool = False,
) -> Charge:
    wallet = lock_wallet(db, tenant_id)
    charge = db.scalar(
        select(Charge)
        .where(Charge.tenant_id == tenant_id, Charge.business_key == key)
        .execution_options(populate_existing=True)
    )
    if charge and charge.status in {"reserved", "settled"}:
        return charge
    # Retry uses the original quote, even if deployment prices have since changed.
    if charge and kind == "script" and get_settings().billing_text_mode == "tokens":
        # Released legacy requests must not charge both the old tariff and actual tokens.
        amount = 0
        charge.amount_cents = 0
        charge.price_snapshot = {**charge.price_snapshot, **price}
    else:
        amount = charge.amount_cents if charge else amount
    if amount < 0:
        raise ValueError("Negative charge")
    if (available(wallet) <= 0 if allow_overdraft else available(wallet) < amount):
        raise ApiError(409, ErrorCode.WALLET_INSUFFICIENT_BALANCE)
    bonus = min(max(0, wallet.bonus_cents - wallet.frozen_bonus_cents), amount)
    paid = amount - bonus
    wallet.frozen_bonus_cents += bonus
    wallet.frozen_paid_cents += paid
    if charge:
        charge.status = "reserved"
        charge.attempt += 1
        charge.bonus_cents, charge.paid_cents = bonus, paid
    else:
        charge = Charge(
            tenant_id=tenant_id,
            business_key=key,
            kind=kind,
            title=title[:300],
            amount_cents=amount,
            paid_cents=paid,
            bonus_cents=bonus,
            status="reserved",
            attempt=1,
            price_snapshot=price,
        )
        db.add(charge)
    db.flush()
    _event(db, wallet, charge, "reserve", frozen=amount)
    return charge


def transition(db: Session, tenant_id: UUID, key: str, settle: bool) -> None:
    wallet = lock_wallet(db, tenant_id)
    charge = db.scalar(
        select(Charge)
        .where(Charge.tenant_id == tenant_id, Charge.business_key == key)
        .execution_options(populate_existing=True)
    )
    if charge is None or charge.status == "settled" or (not settle and charge.status == "released"):
        return
    if charge.status != "reserved":
        raise ApiError(409, ErrorCode.BILLING_STATE_INVALID)
    wallet.frozen_bonus_cents -= charge.bonus_cents
    wallet.frozen_paid_cents -= charge.paid_cents
    if settle:
        wallet.bonus_cents -= charge.bonus_cents
        wallet.paid_cents -= charge.paid_cents
    charge.status = "settled" if settle else "released"
    _event(
        db,
        wallet,
        charge,
        "consume" if settle else "release",
        paid=-charge.paid_cents if settle else 0,
        bonus=-charge.bonus_cents if settle else 0,
        frozen=-charge.amount_cents,
    )


def video_reserve(db: Session, run) -> None:
    quote = (run.output_manifest or {}).get("billing_quote")
    if quote:
        reserve(
            db,
            run.tenant_id,
            f"video:{run.id}",
            quote["amount_cents"],
            "video_hold" if quote.get("video_billing_mode") == "tokens" else "video",
            quote["title"],
            quote,
            allow_overdraft=quote.get("video_billing_mode") == "tokens",
        )


def video_finish(db: Session, run, success: bool) -> None:
    quote = (run.output_manifest or {}).get("billing_quote")
    if quote and quote.get("video_billing_mode") == "tokens":
        from lifereel_api.modules.billing.video import settle_run

        settle_run(db, run, success)
    elif quote:
        transition(db, run.tenant_id, f"video:{run.id}", success)


def debit_actual(db: Session, tenant_id: UUID, key: str, amount: int, title: str, price: dict):
    """Settle already-authorized consumption, even if it creates a cash debt."""
    if amount < 0:
        raise ValueError("Negative charge")
    wallet = lock_wallet(db, tenant_id)
    existing = db.scalar(select(Charge).where(
        Charge.tenant_id == tenant_id, Charge.business_key == key,
    ))
    if existing:
        if existing.status != "settled":
            raise ApiError(409, ErrorCode.BILLING_STATE_INVALID)
        return existing
    bonus = min(max(0, wallet.bonus_cents - wallet.frozen_bonus_cents), amount)
    paid = amount - bonus
    wallet.bonus_cents -= bonus
    wallet.paid_cents -= paid
    charge = Charge(
        tenant_id=tenant_id, business_key=key, kind="tokens", title=title[:300],
        amount_cents=amount, bonus_cents=bonus, paid_cents=paid, status="settled",
        attempt=1, price_snapshot=price,
    )
    db.add(charge)
    db.flush()
    _event(db, wallet, charge, "consume", paid=-paid, bonus=-bonus)
    return charge

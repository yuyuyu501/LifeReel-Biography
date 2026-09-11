"""Ark standard online text tariff, verified 2026-09-11. No guessed usage."""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing import service
from lifereel_api.modules.billing.models import Charge, UsageEvent

VERSION = "ark-character-2026-09-11-x1.5"
SOURCE = "https://docs.volcengine.com/docs/82379/1544106?lang=zh"
MODEL = "doubao-seed-character-260628"
NANO_PER_CENT = 10_000_000
MAX_OUTPUT = 8192
RESERVE_CENTS = 40


def enabled() -> bool:
    return get_settings().billing_text_mode == "tokens"


def quote(model: str, usage: dict) -> dict:
    if model != MODEL:
        raise ValueError("unpriced_model")
    if not isinstance(usage, dict):
        raise ValueError("invalid_usage")
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    details = usage.get("prompt_tokens_details") or {}
    if not isinstance(details, dict):
        raise ValueError("invalid_usage")
    cached = details.get("cached_tokens", 0)
    if any(type(n) is not int or n < 0 for n in (prompt, completion, cached)):
        raise ValueError("missing_or_invalid_usage")
    if cached > prompt or prompt > 128_000 or completion > MAX_OUTPUT:
        raise ValueError("usage_outside_tariff")
    if details.get("audio_tokens") or usage.get("cache_creation_input_tokens"):
        raise ValueError("unsupported_usage_category")
    # Integer nano-CNY/token: 0.80 CNY/million = 800 nano-CNY/token.
    input_rate, output_rate = (800, 2000) if prompt <= 32_000 else (1200, 6000)
    cost = (prompt - cached) * input_rate + cached * 160 + completion * output_rate
    return {
        "version": VERSION,
        "source": SOURCE,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cached_tokens": cached,
        "official_cost_nano": cost,
        "retail_nano": cost * 3 // 2,
        "markup": "1.5",
        "input_cny_per_million": str(input_rate / 1000),
        "output_cny_per_million": str(output_rate / 1000),
        "cached_cny_per_million": "0.16",
    }


def begin(base_url: str, model: str, context: tuple | None) -> str | None:
    if not enabled() or context is None:
        return None
    url = urlparse(base_url)
    if (url.scheme, url.netloc, url.path.rstrip("/"), model) != (
        "https",
        "ark.cn-beijing.volces.com",
        "/api/v3",
        MODEL,
    ):
        raise ApiError(503, ErrorCode.BILLING_MODEL_UNPRICED)
    tenant_id, operation, reference = context
    key = f"token-hold:{uuid4()}"
    with SessionLocal() as db:
        service.lock_wallet(db, tenant_id)
        holds = list(
            db.scalars(
                select(Charge).where(
                    Charge.tenant_id == tenant_id,
                    Charge.kind == "token_hold",
                    Charge.status == "reserved",
                )
            )
        )
        # Pausing on uncertain receipts prevents retries from accumulating holds.
        if any(
            hold.price_snapshot.get("pending")
            or hold.created_at.replace(tzinfo=UTC) < datetime.now(UTC) - timedelta(minutes=5)
            for hold in holds
        ):
            raise ApiError(409, ErrorCode.BILLING_USAGE_PENDING)
        service.reserve(
            db,
            tenant_id,
            key,
            RESERVE_CENTS,
            "token_hold",
            "AI 用量预冻结",
            {
                "version": VERSION,
                "operation": operation,
                "reference": reference,
            },
        )
        db.commit()
    return key


def settle(db, event, reservation: str) -> None:
    wallet = service.lock_wallet(db, event.tenant_id)
    if event.metering.get("status") in {"settled", "duplicate", "released"}:
        return
    hold = db.scalar(
        select(Charge).where(
            Charge.tenant_id == event.tenant_id,
            Charge.business_key == reservation,
        )
    )
    if hold is None or hold.kind != "token_hold" or hold.status != "reserved":
        raise ApiError(409, ErrorCode.BILLING_STATE_INVALID)
    if event.provider_request_id:
        previous = db.scalars(
            select(UsageEvent).where(
                UsageEvent.tenant_id == event.tenant_id,
                UsageEvent.model == event.model,
                UsageEvent.provider_request_id == event.provider_request_id,
                UsageEvent.id != event.id,
            )
        )
        if any(row.metering.get("status") == "settled" for row in previous):
            service.transition(db, event.tenant_id, reservation, False)
            event.metering = {"status": "duplicate", "reservation": reservation}
            return
    try:
        price = quote(event.model, event.usage)
    except ValueError as exc:
        # Unknown receipts require reconciliation; never treat them as zero tokens.
        event.metering = {"status": "pending", "reason": str(exc), "reservation": reservation}
        hold.price_snapshot = {**hold.price_snapshot, "pending": True}
        return
    service.transition(db, event.tenant_id, reservation, False)
    nano = wallet.token_remainder_nano + price["retail_nano"]
    cents, remainder = divmod(nano, NANO_PER_CENT)
    if cents:
        key = f"token-usage:{event.id}"
        service.reserve(db, event.tenant_id, key, cents, "tokens", "AI 实际用量", price)
        service.transition(db, event.tenant_id, key, True)
    wallet.token_remainder_nano = remainder
    event.metering = {
        **price,
        "status": "settled",
        "charged_cents": cents,
        "remainder_nano": remainder,
        "reservation": reservation,
    }

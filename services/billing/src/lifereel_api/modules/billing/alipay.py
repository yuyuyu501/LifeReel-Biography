"""Alipay page checkout and RSA2-verified settlement. No browser assertion credits money."""

import base64
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.models import utcnow
from lifereel_api.modules.billing import service
from lifereel_api.modules.billing.models import LedgerEntry, RechargeOrder

GATEWAY = "https://openapi.alipay.com/gateway.do"
SETTLEMENT = "alipay_page"


def private_key():
    raw = Path(get_settings().alipay_private_key_path).read_bytes().strip()
    key = (
        serialization.load_pem_private_key(raw, password=None)
        if raw.startswith(b"-----")
        else serialization.load_der_private_key(base64.b64decode(raw), password=None)
    )
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise ValueError("RSA2048 private key required")
    return key


def public_key():
    raw = Path(get_settings().alipay_public_key_path).read_bytes().strip()
    key = (
        serialization.load_pem_public_key(raw)
        if raw.startswith(b"-----")
        else serialization.load_der_public_key(base64.b64decode(raw))
    )
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
        raise ValueError("RSA2048 public key required")
    return key


def configured():
    s = get_settings()
    if not re.fullmatch(r"\d{16}", s.alipay_app_id):
        return False
    if not s.alipay_notify_url.startswith("https://") or not s.alipay_return_url.startswith(
        "https://"
    ):
        return False
    try:
        private_key()
        public_key()
    except (OSError, ValueError, TypeError):
        return False
    return True


def canonical(params):
    return "&".join(f"{key}={value}" for key, value in sorted(params.items()) if value != "")


def verify(content, signature):
    try:
        public_key().verify(
            base64.b64decode(signature, validate=True),
            content.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except (InvalidSignature, ValueError, TypeError, OSError) as exc:
        raise ApiError(400, ErrorCode.PAYMENT_VERIFICATION_FAILED) from exc


def parameters(method, biz, **extra):
    s = get_settings()
    params = {
        "app_id": s.alipay_app_id,
        "method": method,
        "format": "JSON",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "biz_content": json.dumps(biz, ensure_ascii=False, separators=(",", ":")),
        **extra,
    }
    params["sign"] = base64.b64encode(
        private_key().sign(canonical(params).encode(), padding.PKCS1v15(), hashes.SHA256())
    ).decode()
    return params


def checkout_url(order):
    s = get_settings()
    if (
        not s.alipay_enabled
        or not configured()
        or order.settlement != SETTLEMENT
        or order.alipay_app_id != s.alipay_app_id
        or order.status != "pending"
    ):
        raise ApiError(409, ErrorCode.RECHARGE_STATE_INVALID)
    return (
        GATEWAY
        + "?"
        + urlencode(
            parameters(
                "alipay.trade.page.pay",
                {
                    "out_trade_no": order.id.hex,
                    "total_amount": f"{Decimal(order.amount_cents) / 100:.2f}",
                    "subject": "LifeReel 服务额度",
                    "product_code": "FAST_INSTANT_TRADE_PAY",
                    "timeout_express": "30m",
                },
                notify_url=s.alipay_notify_url,
                return_url=s.alipay_return_url,
            )
        )
    )


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate response field")
        result[key] = value
    return result


def verified_response(text, method):
    """Keep the exact JSON object bytes: reserializing would change the signature."""
    decoder = json.JSONDecoder(object_pairs_hook=unique_object)
    envelope = decoder.decode(text)
    name = method.replace(".", "_") + "_response"
    if not isinstance(envelope, dict) or name not in envelope or "sign" not in envelope:
        raise ApiError(502, ErrorCode.PAYMENT_VERIFICATION_FAILED)
    pos = text.index("{") + 1
    while pos < len(text):
        pos += len(text[pos:]) - len(text[pos:].lstrip())
        key, pos = decoder.raw_decode(text, pos)
        pos += len(text[pos:]) - len(text[pos:].lstrip())
        if text[pos] != ":":
            raise ValueError("Invalid response")
        pos += 1
        pos += len(text[pos:]) - len(text[pos:].lstrip())
        start = pos
        value, pos = decoder.raw_decode(text, pos)
        if key == name:
            verify(text[start:pos], envelope["sign"])
            if not isinstance(value, dict):
                raise ValueError("Invalid response object")
            return value
        pos += len(text[pos:]) - len(text[pos:].lstrip())
        if text[pos] != ",":
            break
        pos += 1
    raise ValueError("Missing response")


def query_order(order):
    method = "alipay.trade.query"
    try:
        with httpx.Client(timeout=8, trust_env=False) as client:
            response = client.post(GATEWAY, data=parameters(method, {"out_trade_no": order.id.hex}))
            response.raise_for_status()
        return verified_response(response.text, method)
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        raise ApiError(502, ErrorCode.PAYMENT_QUERY_FAILED) from exc


def credit(db: Session, row: RechargeOrder, data: dict, *, from_query: bool = False):
    if row.settlement != SETTLEMENT or row.payment_method != "alipay":
        raise ApiError(400, ErrorCode.PAYMENT_VERIFICATION_FAILED)
    s = get_settings()
    if row.alipay_app_id != s.alipay_app_id:
        raise ApiError(400, ErrorCode.PAYMENT_VERIFICATION_FAILED)
    if data.get("out_trade_no") != row.id.hex:
        raise ApiError(400, ErrorCode.PAYMENT_VERIFICATION_FAILED)
    if (
        s.alipay_seller_id
        and (not from_query or "seller_id" in data)
        and data.get("seller_id") != s.alipay_seller_id
    ):
        raise ApiError(400, ErrorCode.PAYMENT_VERIFICATION_FAILED)
    amount = data.get("total_amount", "")
    if not isinstance(amount, str) or not re.fullmatch(r"\d+(\.\d{1,2})?", amount):
        raise ApiError(400, ErrorCode.PAYMENT_VERIFICATION_FAILED)
    if Decimal(amount) * 100 != row.amount_cents:
        raise ApiError(400, ErrorCode.RECHARGE_AMOUNT_MISMATCH)
    reference = data.get("trade_no", "")
    if not isinstance(reference, str) or not re.fullmatch(r"\d{10,64}", reference):
        raise ApiError(400, ErrorCode.PAYMENT_VERIFICATION_FAILED)
    # Same lock order as manual review: wallet, then order, before checking state.
    wallet = service.lock_wallet(db, row.tenant_id)
    row = db.scalar(
        select(RechargeOrder)
        .where(RechargeOrder.id == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.status == "credited":
        if row.verified_reference != reference:
            raise ApiError(409, ErrorCode.RECHARGE_RECEIPT_USED)
        return row
    if row.status != "pending":
        raise ApiError(409, ErrorCode.RECHARGE_STATE_INVALID)
    row.verified_reference = reference
    row.status = "credited"
    row.reviewed_by = "alipay:RSA2"
    row.reviewed_at = utcnow()
    wallet.paid_cents += row.amount_cents
    db.add(
        LedgerEntry(
            tenant_id=row.tenant_id,
            event_key=f"recharge:{row.id}",
            event="recharge",
            title="支付宝充值",
            amount_cents=row.amount_cents,
            paid_delta=row.amount_cents,
            available_after_cents=service.available(wallet),
        )
    )
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, ErrorCode.RECHARGE_RECEIPT_USED) from exc
    return row


def notify(db: Session, params: dict):
    if params.get("sign_type") != "RSA2" or params.get("app_id") != get_settings().alipay_app_id:
        raise ApiError(400, ErrorCode.PAYMENT_VERIFICATION_FAILED)
    verify(
        canonical(
            {key: value for key, value in params.items() if key not in {"sign", "sign_type"}}
        ),
        params.get("sign", ""),
    )
    try:
        order_id = UUID(params.get("out_trade_no", ""))
    except ValueError as exc:
        raise ApiError(400, ErrorCode.PAYMENT_VERIFICATION_FAILED) from exc
    row = db.get(RechargeOrder, order_id)
    if row is None or row.settlement != SETTLEMENT or row.alipay_app_id != params["app_id"]:
        raise ApiError(404, ErrorCode.RECHARGE_NOT_FOUND)
    if params.get("trade_status") in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        credit(db, row, params)
    db.commit()


def reconcile(db: Session, row: RechargeOrder):
    if row.settlement != SETTLEMENT or row.status != "pending":
        return row
    if row.alipay_app_id != get_settings().alipay_app_id:
        raise ApiError(409, ErrorCode.RECHARGE_STATE_INVALID)
    now = utcnow()
    claimed = db.execute(
        update(RechargeOrder)
        .where(
            RechargeOrder.id == row.id,
            RechargeOrder.status == "pending",
            or_(
                RechargeOrder.payment_checked_at.is_(None),
                RechargeOrder.payment_checked_at < now - timedelta(seconds=15),
            ),
        )
        .values(payment_checked_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    if not claimed:
        db.refresh(row)
        return row
    data = query_order(row)
    if data.get("code") == "40004" and data.get("sub_code") == "ACQ.TRADE_NOT_EXIST":
        return row
    if data.get("code") != "10000":
        raise ApiError(502, ErrorCode.PAYMENT_QUERY_FAILED)
    if data.get("trade_status") in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        # The direct, RSA2-verified query is scoped to our signed APPID request.
        row = credit(db, row, data, from_query=True)
        db.commit()
    elif data.get("trade_status") == "TRADE_CLOSED":
        row = db.scalar(
            select(RechargeOrder)
            .where(RechargeOrder.id == row.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row.status == "pending":
            row.status = "cancelled"
        db.commit()
    return row


def reconcile_pending():
    from lifereel_api.core.database import SessionLocal

    if not configured():
        return
    with SessionLocal() as db:
        rows = db.scalars(
            select(RechargeOrder)
            .where(
                RechargeOrder.settlement == SETTLEMENT,
                RechargeOrder.status == "pending",
                RechargeOrder.alipay_app_id == get_settings().alipay_app_id,
                RechargeOrder.created_at >= utcnow() - timedelta(days=2),
            )
            .order_by(
                RechargeOrder.payment_checked_at.asc().nullsfirst(),
                RechargeOrder.created_at.asc(),
            )
            .limit(5)
        ).all()
        for row in rows:
            try:
                reconcile(db, row)
            except ApiError:
                db.rollback()

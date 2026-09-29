from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from datetime import UTC, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.models import utcnow
from lifereel_api.modules.auth.models import SmsChallenge
from lifereel_api.modules.auth.schemas import SmsVerification
from lifereel_api.modules.auth.throttle import limit

logger = logging.getLogger(__name__)


def template_for(purpose: str) -> str | None:
    s = get_settings()
    if purpose == "register":
        return s.sms_template_code
    if purpose == "reset_password":
        return s.sms_reset_template_code or s.sms_security_template_code
    return s.sms_security_template_code


def configured(purpose: str = "register") -> bool:
    s = get_settings()
    return bool(
        s.sms_enabled
        and s.sms_sign_name
        and template_for(purpose)
        and s.auth_token_secret
        and (s.sms_access_key_id or s.s3_access_key)
        and (s.sms_access_key_secret or s.s3_secret_key)
    )


def send_code(phone: str, code: str, purpose: str) -> None:
    if not configured(purpose):
        raise ApiError(503, ErrorCode.SMS_NOT_CONFIGURED)
    from alibabacloud_dysmsapi20170525.client import Client
    from alibabacloud_dysmsapi20170525.models import SendSmsRequest
    from alibabacloud_tea_openapi.utils_models import Config
    from darabonba.runtime import RuntimeOptions

    s = get_settings()
    client = Client(
        Config(
            access_key_id=s.sms_access_key_id or s.s3_access_key,
            access_key_secret=s.sms_access_key_secret or s.s3_secret_key,
            endpoint="dysmsapi.aliyuncs.com",
            region_id="cn-hangzhou",
        )
    )
    template = template_for(purpose)
    try:
        response = client.send_sms_with_options(
            SendSmsRequest(
                phone_numbers=phone,
                sign_name=s.sms_sign_name,
                template_code=template,
                template_param=json.dumps({s.sms_code_parameter: code}),
            ),
            RuntimeOptions(connect_timeout=5000, read_timeout=10000, autoretry=False),
        )
    except Exception as exc:
        # SDK errors may contain signed request details; never log their body or credentials.
        logger.warning("SMS transport failed: %s", type(exc).__name__)
        raise ApiError(502, ErrorCode.SMS_SEND_FAILED) from None
    if response.body is None or response.body.code != "OK":
        logger.warning("SMS provider rejected request: %s", getattr(response.body, "code", None))
        raise ApiError(502, ErrorCode.SMS_SEND_FAILED)


def digest(challenge_id: UUID, phone: str, purpose: str, code: str) -> str:
    secret = get_settings().auth_token_secret
    if not secret:
        raise ApiError(503, ErrorCode.SMS_NOT_CONFIGURED)
    return hmac.new(
        secret.encode(), f"{challenge_id}:{phone}:{purpose}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def issue(db: Session, phone: str, purpose: str, address: str) -> dict:
    if not configured(purpose):
        raise ApiError(503, ErrorCode.SMS_NOT_CONFIGURED)
    limit("sms-ip-hour", address, 20, 3600)
    limit("sms-phone-minute", phone, 1, 60)
    limit("sms-phone-hour", phone, 5, 3600)
    limit("sms-phone-day", phone, 10, 86400)
    limit("sms-global-day", "all", get_settings().sms_daily_limit, 86400)
    code = f"{secrets.randbelow(1000000):06d}"
    challenge_id = uuid4()
    send_code(phone, code, purpose)
    now = utcnow()
    db.execute(
        update(SmsChallenge)
        .where(
            SmsChallenge.phone == phone,
            SmsChallenge.purpose == purpose,
            SmsChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    db.execute(delete(SmsChallenge).where(SmsChallenge.expires_at < now - timedelta(days=1)))
    ttl = get_settings().sms_code_ttl_seconds
    db.add(
        SmsChallenge(
            id=challenge_id,
            phone=phone,
            purpose=purpose,
            code_hash=digest(challenge_id, phone, purpose, code),
            expires_at=now + timedelta(seconds=ttl),
        )
    )
    db.commit()
    return {"challenge_id": challenge_id, "expires_in": ttl, "retry_after": 60}


def consume(db: Session, payload: SmsVerification, purpose: str) -> None:
    challenge = db.scalar(
        select(SmsChallenge)
        .where(
            SmsChallenge.id == payload.challenge_id,
            SmsChallenge.phone == payload.phone,
            SmsChallenge.purpose == purpose,
        )
        .with_for_update()
    )
    if not challenge or challenge.consumed_at:
        raise ApiError(400, ErrorCode.SMS_CODE_INVALID)
    if challenge.expires_at.replace(tzinfo=UTC) <= utcnow():
        raise ApiError(400, ErrorCode.SMS_CODE_EXPIRED)
    if challenge.attempts >= 5:
        raise ApiError(429, ErrorCode.SMS_CODE_LOCKED)
    if not hmac.compare_digest(
        challenge.code_hash, digest(challenge.id, payload.phone, purpose, payload.code)
    ):
        challenge.attempts += 1
        db.commit()
        raise ApiError(400, ErrorCode.SMS_CODE_INVALID)
    # The caller commits this consumption atomically with the account mutation.
    challenge.consumed_at = utcnow()

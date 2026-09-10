from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import re
from datetime import UTC, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.models import utcnow
from lifereel_api.modules.evidence.models import EvidenceUpload, SourceAsset
from lifereel_api.modules.evidence.schemas import DirectUploadCreate, DirectUploadRead
from lifereel_api.modules.evidence.service import (
    evidence_kind_for_mime,
    evidence_limit_bytes,
    get_asset,
    sniff_evidence_kind,
)
from lifereel_api.modules.evidence.storage import S3PrivateStorage
from lifereel_api.modules.identity.models import Person, Tenant
from lifereel_api.modules.interview.models import InterviewSession

logger = logging.getLogger(__name__)
PROJECT_PREFIX = "LifeReel-Biography/"
STAGING_PREFIX = f"{PROJECT_PREFIX}uploads/staging/"
UPLOAD_SECONDS = 3600


def enabled() -> bool:
    return get_settings().oss_direct_upload_enabled


def upload_endpoint() -> str:
    settings = get_settings()
    endpoint = urlsplit(settings.s3_endpoint_url)
    if (
        not enabled()
        or settings.storage_backend != "s3"
        or endpoint.scheme != "https"
        or not re.fullmatch(r"oss-[a-z0-9-]+\.aliyuncs\.com", endpoint.netloc)
        or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", settings.s3_bucket)
    ):
        raise ApiError(503, ErrorCode.EVIDENCE_UPLOAD_UNAVAILABLE)
    return f"https://{settings.s3_bucket}.{endpoint.netloc}"


def validate_scope(db: Session, tenant_id: UUID, subject_id: UUID, session_id: UUID | None):
    subject = db.scalar(
        select(Person).where(
            Person.id == subject_id,
            Person.tenant_id == tenant_id,
        )
    )
    if subject is None:
        raise ApiError(404, ErrorCode.SUBJECT_NOT_FOUND)
    if (
        session_id
        and db.scalar(
            select(InterviewSession).where(
                InterviewSession.id == session_id,
                InterviewSession.subject_id == subject_id,
                InterviewSession.tenant_id == tenant_id,
            )
        )
        is None
    ):
        raise ApiError(404, ErrorCode.INTERVIEW_NOT_FOUND)


def prepare(db: Session, tenant_id: UUID, payload: DirectUploadCreate) -> DirectUploadRead:
    url = upload_endpoint()
    validate_scope(db, tenant_id, payload.subject_id, payload.interview_session_id)
    mime = payload.mime_type or "application/octet-stream"
    if mime == "application/octet-stream":
        mime = mimetypes.guess_type(payload.original_filename)[0] or mime
    if evidence_kind_for_mime(mime) != payload.kind:
        raise ApiError(415, ErrorCode.EVIDENCE_TYPE_UNSUPPORTED)
    limit = evidence_limit_bytes(payload.kind)
    if payload.byte_size > limit:
        raise ApiError(
            413, ErrorCode.EVIDENCE_FILE_TOO_LARGE, {"kind": payload.kind, "limit_bytes": limit}
        )
    # Serialize permit issuance per tenant to bound abandoned and concurrent uploads.
    db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    now = utcnow()
    count = db.scalar(
        select(func.count())
        .select_from(EvidenceUpload)
        .where(
            EvidenceUpload.tenant_id == tenant_id,
            EvidenceUpload.asset_id.is_(None),
            EvidenceUpload.expires_at > now,
        )
    )
    if count >= 10:
        raise ApiError(429, ErrorCode.EVIDENCE_UPLOAD_BUSY)
    upload_id = uuid4()
    upload = EvidenceUpload(
        id=upload_id,
        tenant_id=tenant_id,
        subject_id=payload.subject_id,
        interview_session_id=payload.interview_session_id,
        original_filename=Path(payload.original_filename).name,
        mime_type=mime,
        kind=payload.kind,
        byte_size=payload.byte_size,
        consent_scope=payload.consent_scope,
        storage_key=f"{STAGING_PREFIX}{tenant_id}/{payload.subject_id}/{upload_id}",
        expires_at=now + timedelta(seconds=UPLOAD_SECONDS),
    )
    settings = get_settings()
    fields = {
        "key": upload.storage_key,
        "Content-Type": mime,
        "success_action_status": "204",
        "x-oss-forbid-overwrite": "true",
    }
    # OSS native POST policy: exact object and size, no overwrite or public ACL.
    policy = base64.b64encode(
        json.dumps(
            {
                "expiration": upload.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "conditions": [
                    {"bucket": settings.s3_bucket},
                    *[{key: value} for key, value in fields.items()],
                    ["content-length-range", payload.byte_size, payload.byte_size],
                ],
            }
        ).encode()
    ).decode()
    fields.update(
        {
            "OSSAccessKeyId": settings.s3_access_key,
            "policy": policy,
            "Signature": base64.b64encode(
                hmac.new(
                    settings.s3_secret_key.encode(),
                    policy.encode(),
                    hashlib.sha1,
                ).digest()
            ).decode(),
        }
    )
    db.add(upload)
    db.commit()
    return DirectUploadRead(
        upload_id=upload_id,
        url=url,
        fields=fields,
        expires_at=upload.expires_at,
    )


def complete(db: Session, tenant_id: UUID, upload_id: UUID) -> SourceAsset:
    upload_endpoint()
    upload = db.scalar(
        select(EvidenceUpload)
        .where(
            EvidenceUpload.id == upload_id,
            EvidenceUpload.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if upload is None:
        raise ApiError(404, ErrorCode.EVIDENCE_UPLOAD_NOT_FOUND)
    if upload.asset_id:
        return get_asset(db, tenant_id, upload.asset_id)
    if upload.expires_at.replace(tzinfo=UTC) <= utcnow():
        raise ApiError(410, ErrorCode.EVIDENCE_UPLOAD_EXPIRED)
    validate_scope(db, tenant_id, upload.subject_id, upload.interview_session_id)
    storage = S3PrivateStorage()
    try:
        return verify_and_commit(db, tenant_id, upload, storage)
    except (ClientError, BotoCoreError):
        # Never expose provider XML, signatures, or credentials to clients/logs.
        raise ApiError(502, ErrorCode.EVIDENCE_UPLOAD_FAILED) from None


def verify_and_commit(
    db: Session,
    tenant_id: UUID,
    upload: EvidenceUpload,
    storage: S3PrivateStorage,
) -> SourceAsset:
    client, bucket, key = storage.client, storage.bucket, upload.storage_key
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if str(exc.response["Error"]["Code"]) in {"404", "NoSuchKey", "NotFound"}:
            raise ApiError(400, ErrorCode.EVIDENCE_UPLOAD_NOT_FOUND) from None
        raise
    if (
        head["ContentLength"] != upload.byte_size
        or head["ContentLength"] > evidence_limit_bytes(upload.kind)
        or head.get("ContentType") != upload.mime_type
    ):
        raise ApiError(400, ErrorCode.EVIDENCE_UPLOAD_INVALID)
    # Stream verification in bounded memory; never trust a client-provided hash.
    response = client.get_object(Bucket=bucket, Key=key, IfMatch=head["ETag"])
    digest, size, header = hashlib.sha256(), 0, b""
    body = response["Body"]
    try:
        for chunk in body.iter_chunks(chunk_size=1024 * 1024):
            if not chunk:
                continue
            header = (header + chunk[:64])[:64]
            size += len(chunk)
            if size > upload.byte_size:
                raise ApiError(400, ErrorCode.EVIDENCE_UPLOAD_INVALID)
            digest.update(chunk)
    finally:
        body.close()
    if size != upload.byte_size or sniff_evidence_kind(header, upload.kind) != upload.kind:
        raise ApiError(415, ErrorCode.EVIDENCE_TYPE_UNSUPPORTED)
    sha256 = digest.hexdigest()
    existing_query = select(SourceAsset).where(
        SourceAsset.tenant_id == tenant_id,
        SourceAsset.subject_id == upload.subject_id,
        SourceAsset.sha256 == sha256,
    )
    asset = db.scalar(existing_query)
    if asset is None:
        suffix = Path(upload.original_filename).suffix.lower()[:12]
        suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ""
        final_key = (
            f"{PROJECT_PREFIX}evidence/{tenant_id}/{upload.subject_id}/"
            f"{sha256[:2]}/{sha256}{suffix}"
        )
        # Server-side copy keeps committed assets unreachable by upload credentials.
        client.copy_object(
            Bucket=bucket,
            Key=final_key,
            CopySource={"Bucket": bucket, "Key": key},
            CopySourceIfMatch=head["ETag"],
            MetadataDirective="REPLACE",
            ContentType=upload.mime_type,
        )
        try:
            with db.begin_nested():
                asset = SourceAsset(
                    tenant_id=tenant_id,
                    subject_id=upload.subject_id,
                    interview_session_id=upload.interview_session_id,
                    kind=upload.kind,
                    original_filename=upload.original_filename,
                    mime_type=upload.mime_type,
                    byte_size=size,
                    sha256=sha256,
                    storage_key=final_key,
                    consent_scope=upload.consent_scope,
                    status="ready",
                )
                db.add(asset)
                db.flush()
        except IntegrityError:
            asset = db.scalar(existing_query)
            if asset is None:
                raise
    upload.asset_id = asset.id
    db.commit()
    try:
        client.delete_object(Bucket=bucket, Key=key)
    except (ClientError, BotoCoreError):
        logger.warning("OSS staging cleanup deferred: upload=%s", upload.id)
    return asset

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.evidence import direct_uploads, service
from lifereel_api.modules.evidence.schemas import (
    DirectUploadComplete,
    DirectUploadCreate,
    DirectUploadRead,
    EvidenceObservationRead,
    SourceAssetRead,
    TranscriptCreate,
    TranscriptRead,
    TranscriptRevisionCreate,
    TranscriptSegmentRead,
    TranscriptVersionRead,
)
from lifereel_api.modules.evidence.storage import private_storage

router = APIRouter(prefix="/evidence", tags=["evidence"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]
RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")


def range_bounds(value: str, size: int) -> tuple[int, int]:
    match = RANGE_PATTERN.fullmatch(value.strip())
    if not match:
        raise ApiError(
            status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            ErrorCode.EVIDENCE_RANGE_INVALID,
            {"size": size},
        )
    first, last = match.groups()
    if not first:
        suffix_length = int(last or "0")
        if suffix_length <= 0:
            raise ApiError(
                status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                ErrorCode.EVIDENCE_RANGE_INVALID,
                {"size": size},
            )
        return max(0, size - suffix_length), size - 1
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        raise ApiError(
            status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            ErrorCode.EVIDENCE_RANGE_INVALID,
            {"size": size},
        )
    return start, end


def content_disposition(filename: str) -> str:
    suffix = Path(filename).suffix.lower()[:12]
    safe_suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ""
    fallback = f"evidence{safe_suffix}"
    return f"inline; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def transcript_read(db: Session, tenant_id: UUID, transcript_id: UUID) -> TranscriptRead:
    transcript, version_payloads = service.get_transcript_payload(db, tenant_id, transcript_id)
    versions = []
    for version, segments in version_payloads:
        version_read = TranscriptVersionRead.model_validate(version).model_copy(
            update={"segments": [TranscriptSegmentRead.model_validate(item) for item in segments]}
        )
        versions.append(version_read)
    return TranscriptRead.model_validate(transcript).model_copy(update={"versions": versions})


@router.post("/assets", response_model=SourceAssetRead, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    db: Db,
    tenant_id: Tenant,
    subject_id: Annotated[UUID, Form()],
    kind: Annotated[str, Form(pattern="^(audio|photo|video|document)$")],
    file: Annotated[UploadFile, File()],
    interview_session_id: Annotated[UUID | None, Form()] = None,
    consent_scope: Annotated[str, Form(pattern="^(private|family|friends|public)$")] = "private",
) -> SourceAssetRead:
    return await service.create_asset(
        db,
        tenant_id,
        subject_id,
        interview_session_id,
        kind,
        consent_scope,
        file,
    )


@router.post("/assets/direct-upload", response_model=DirectUploadRead)
def direct_upload(payload: DirectUploadCreate, db: Db, tenant_id: Tenant) -> DirectUploadRead:
    return direct_uploads.prepare(db, tenant_id, payload)


@router.get("/upload-settings")
def upload_settings(tenant_id: Tenant) -> dict[str, bool]:
    return {"direct_upload": direct_uploads.enabled()}


@router.post(
    "/assets/complete-direct-upload",
    response_model=SourceAssetRead,
    status_code=status.HTTP_201_CREATED,
)
def complete_direct_upload(
    payload: DirectUploadComplete, db: Db, tenant_id: Tenant
) -> SourceAssetRead:
    return direct_uploads.complete(db, tenant_id, payload.upload_id)


@router.get("/assets", response_model=list[SourceAssetRead])
def assets(db: Db, tenant_id: Tenant, subject_id: UUID | None = None) -> list[SourceAssetRead]:
    return service.list_assets(db, tenant_id, subject_id)


@router.get("/assets/{asset_id}/content")
def asset_content(
    asset_id: UUID,
    db: Db,
    tenant_id: Tenant,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    asset = service.get_asset(db, tenant_id, asset_id)
    start, end = (0, asset.byte_size - 1)
    response_status = status.HTTP_200_OK
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": content_disposition(asset.original_filename),
    }
    if range_header:
        start, end = range_bounds(range_header, asset.byte_size)
        response_status = status.HTTP_206_PARTIAL_CONTENT
        headers["Content-Range"] = f"bytes {start}-{end}/{asset.byte_size}"
    headers["Content-Length"] = str(end - start + 1)
    return StreamingResponse(
        private_storage().iter_range(asset.storage_key, start, end),
        status_code=response_status,
        media_type=asset.mime_type,
        headers=headers,
    )


@router.post(
    "/assets/{asset_id}/transcript",
    response_model=TranscriptRead,
    status_code=status.HTTP_201_CREATED,
)
def create_transcript(
    asset_id: UUID, payload: TranscriptCreate, db: Db, tenant_id: Tenant
) -> TranscriptRead:
    transcript = service.create_transcript(db, tenant_id, asset_id, payload)
    return transcript_read(db, tenant_id, transcript.id)


@router.get("/assets/{asset_id}/transcript", response_model=TranscriptRead)
def asset_transcript(asset_id: UUID, db: Db, tenant_id: Tenant) -> TranscriptRead:
    transcript = service.get_transcript_by_asset(db, tenant_id, asset_id)
    return transcript_read(db, tenant_id, transcript.id)


@router.post("/assets/{asset_id}/transcribe", response_model=TranscriptRead)
def transcribe_asset(asset_id: UUID, db: Db, tenant_id: Tenant) -> TranscriptRead:
    transcript = service.transcribe_asset(db, tenant_id, asset_id)
    return transcript_read(db, tenant_id, transcript.id)


@router.post("/assets/{asset_id}/analyze", response_model=EvidenceObservationRead)
def analyze_asset(asset_id: UUID, db: Db, tenant_id: Tenant) -> EvidenceObservationRead:
    return service.analyze_asset(db, tenant_id, asset_id)


@router.get("/assets/{asset_id}/observations", response_model=list[EvidenceObservationRead])
def observations(asset_id: UUID, db: Db, tenant_id: Tenant) -> list[EvidenceObservationRead]:
    return service.list_observations(db, tenant_id, asset_id)


@router.get("/transcripts/{transcript_id}", response_model=TranscriptRead)
def transcript(transcript_id: UUID, db: Db, tenant_id: Tenant) -> TranscriptRead:
    return transcript_read(db, tenant_id, transcript_id)


@router.post("/transcripts/{transcript_id}/revisions", response_model=TranscriptRead)
def revise_transcript(
    transcript_id: UUID,
    payload: TranscriptRevisionCreate,
    db: Db,
    tenant_id: Tenant,
) -> TranscriptRead:
    service.revise_transcript(db, tenant_id, transcript_id, payload)
    return transcript_read(db, tenant_id, transcript_id)

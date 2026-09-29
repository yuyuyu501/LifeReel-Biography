from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.evidence.router import content_disposition
from lifereel_api.modules.evidence.schemas import SourceAssetRead
from lifereel_api.modules.evidence.storage import media_redirect
from lifereel_api.modules.restoration import service
from lifereel_api.modules.restoration.schemas import (
    HistoryRead,
    PhotoRead,
    RestorationRead,
    SaveRequest,
    StartRequest,
)

router = APIRouter(prefix="/photo-restoration", tags=["photo-restoration"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]


@router.get("/settings")
def settings(tenant_id: Tenant):
    return {"enabled": service.enabled(), "max_bytes": service.siliconflow.MAX_BYTES}


@router.post("/photos", response_model=PhotoRead, status_code=201)
async def upload(db: Db, tenant_id: Tenant, file: Annotated[UploadFile, File()]):
    return await service.upload(db, tenant_id, file)


@router.get("/photos/{photo_id}/content")
def original(photo_id: UUID, db: Db, tenant_id: Tenant):
    photo = service.get_photo(db, tenant_id, photo_id)
    redirect = media_redirect(photo.storage_key, photo.mime_type)
    if redirect is not None:
        return redirect
    return Response(
        service.checked_content(photo.storage_key, photo.byte_size, photo.sha256),
        media_type=photo.mime_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/runs", response_model=RestorationRead, status_code=202)
def start(payload: StartRequest, db: Db, tenant_id: Tenant):
    return service.to_read(db, service.start(db, tenant_id, payload))


@router.get("/runs", response_model=HistoryRead)
def history(db: Db, tenant_id: Tenant, page: Annotated[int, Query(ge=1)] = 1):
    return service.history(db, tenant_id, page)


@router.get("/runs/{job_id}", response_model=RestorationRead)
def detail(job_id: UUID, db: Db, tenant_id: Tenant):
    return service.to_read(db, service.get_job(db, tenant_id, job_id))


@router.get("/runs/{job_id}/content")
def result(job_id: UUID, db: Db, tenant_id: Tenant, download: bool = False):
    job = service.get_job(db, tenant_id, job_id)
    output = service.output(job)
    if not download:
        redirect = media_redirect(output["storage_key"], output["mime_type"])
        if redirect is not None:
            return redirect
    photo = service.get_photo(db, tenant_id, UUID(job.payload["photo_id"]))
    disposition = content_disposition(service.filename(photo, job))
    return Response(
        service.checked_content(output["storage_key"], output["byte_size"], output["sha256"]),
        media_type=output["mime_type"],
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": disposition.replace("inline;", "attachment;")
            if download
            else disposition,
        },
    )


@router.post("/runs/{job_id}/save", response_model=SourceAssetRead)
def save(job_id: UUID, payload: SaveRequest, db: Db, tenant_id: Tenant):
    return service.save_to_person(db, tenant_id, job_id, payload.subject_id)

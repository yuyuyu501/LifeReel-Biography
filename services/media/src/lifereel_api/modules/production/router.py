from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import get_db
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.evidence.storage import media_redirect, private_storage
from lifereel_api.modules.jobs.dispatch import require_execution_access
from lifereel_api.modules.production import service
from lifereel_api.modules.production.models import GeneratedAsset, ProductionRun
from lifereel_api.modules.production.recovery import details
from lifereel_api.modules.production.references import build_reference_package
from lifereel_api.modules.production.schemas import (
    GeneratedAssetRead,
    ProductionRecovery,
    ProductionRunRead,
    ProductionStart,
    ReferenceRetry,
    SegmentRegeneration,
)
from lifereel_api.providers.siliconflow import PROMPT_VERSION

router = APIRouter(prefix="/production", tags=["production"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]


@router.get("/settings")
def production_settings(tenant_id: Tenant) -> dict:
    settings = get_settings()
    is_seedance = settings.video_provider in {"volcengine-seedance", "volcengine-seedance-1.5"}
    return {
        "provider": settings.video_provider,
        "model": settings.volcengine_video_model if is_seedance else None,
        "resolution": settings.volcengine_video_resolution if is_seedance else None,
        "ratio": settings.volcengine_video_ratio if is_seedance else None,
        "duration_seconds": settings.volcengine_video_duration if is_seedance else None,
        "generate_audio": settings.volcengine_video_generate_audio if is_seedance else None,
        "mode": (
            "segmented"
            if is_seedance and settings.volcengine_video_model.startswith("doubao-seedance-2-")
            else "single_clip"
        ),
        "max_segment_seconds": 15,
        "reference_style": settings.video_reference_style,
        "reference_prompt_version": (
            PROMPT_VERSION if settings.video_reference_style == "color_redraw" else None
        ),
    }


def to_read(run, assets) -> ProductionRunRead:
    recovery = details(run)
    return ProductionRunRead.model_validate(run).model_copy(
        update={
            "assets": [GeneratedAssetRead.model_validate(item) for item in assets],
            "recovery": ProductionRecovery.model_validate(recovery) if recovery else None,
            "error_message": recovery["code"] if recovery else run.error_message,
        }
    )


@router.post("/runs", response_model=ProductionRunRead, status_code=status.HTTP_201_CREATED)
def start(payload: ProductionStart, db: Db, tenant_id: Tenant) -> ProductionRunRead:
    run = service.start_production(db, tenant_id, payload)
    _, assets = service.get_run_payload(db, tenant_id, run.id)
    return to_read(run, assets)


@router.get("/reference-package")
def reference_package(
    db: Db,
    tenant_id: Tenant,
    subject_id: UUID,
    chapter_id: UUID | None = None,
) -> dict:
    """Preview the chapter-scoped reference selection before starting production."""
    return build_reference_package(db, tenant_id, subject_id, chapter_id)


@router.get("/runs", response_model=list[ProductionRunRead])
def runs(db: Db, tenant_id: Tenant) -> list[ProductionRunRead]:
    return [
        to_read(item, service.get_run_payload(db, tenant_id, item.id)[1])
        for item in service.list_runs(db, tenant_id)
    ]


@router.get("/runs/{run_id}/segments/{index}/quote")
def segment_quote(run_id: UUID, index: int, db: Db, tenant_id: Tenant):
    from lifereel_api.modules.production import regeneration
    return regeneration.quote(db, tenant_id, run_id, index)


@router.get("/runs/{run_id}/progress")
def production_progress(run_id: UUID, db: Db, tenant_id: Tenant):
    from lifereel_api.modules.production.progress import summary
    run, _ = service.get_run_payload(db, tenant_id, run_id)
    return summary(db, run)


@router.post("/runs/{run_id}/segments/{index}/regenerate", response_model=ProductionRunRead)
def regenerate_segment(run_id: UUID, index: int, payload: SegmentRegeneration,
                       db: Db, tenant_id: Tenant):
    from lifereel_api.modules.production import regeneration
    run = regeneration.start(db, tenant_id, run_id, index, payload)
    return to_read(run, service.get_run_payload(db, tenant_id, run.id)[1])


@router.post(
    "/runs/{run_id}/execute",
    response_model=ProductionRunRead,
    dependencies=[Depends(require_execution_access)],
)
def execute(run_id: UUID, db: Db, tenant_id: Tenant) -> ProductionRunRead:
    run = service.execute_run(db, tenant_id, run_id)
    _, assets = service.get_run_payload(db, tenant_id, run.id)
    return to_read(run, assets)


@router.get("/assets/{asset_id}/content")
def asset_content(
    asset_id: UUID, db: Db, tenant_id: Tenant,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    asset = db.get(GeneratedAsset, asset_id)
    if asset is None or asset.tenant_id != tenant_id:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.PRODUCTION_ASSET_NOT_FOUND)
    run = db.get(ProductionRun, asset.production_run_id)
    if run and (run.output_manifest or {}).get("media_retention"):
        raise ApiError(404, ErrorCode.PRODUCTION_ASSET_NOT_FOUND)
    redirect = media_redirect(asset.storage_key, asset.mime_type)
    if redirect is not None:
        return redirect
    return streamed_media(asset.storage_key, asset.mime_type, range_header)


def streamed_media(key: str, mime_type: str, range_header: str | None) -> Response:
    from lifereel_api.modules.evidence.router import range_bounds
    store = private_storage()
    size = store.size(key)
    start, end = range_bounds(range_header, size) if range_header else (0, size - 1)
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, no-store",
               "Content-Length": str(end - start + 1)}
    if range_header:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(store.iter_range(key, start, end), media_type=mime_type,
                             status_code=206 if range_header else 200, headers=headers)


@router.post("/runs/{run_id}/reference", response_model=ProductionRunRead)
def retry_reference(
    run_id: UUID,
    payload: ReferenceRetry,
    db: Db,
    tenant_id: Tenant,
) -> ProductionRunRead:
    from lifereel_api.modules.jobs import service as jobs

    run, assets = service.get_run_payload(db, tenant_id, run_id)
    if not run.job_id:
        raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
    job = jobs.retry_job(db, tenant_id, run.job_id, reference_asset_id=payload.reference_asset_id)
    try:
        jobs.enqueue(job)
    except Exception:
        jobs.fail_job(db, tenant_id, job.id, "WORKER_ERROR", None)
        raise ApiError(503, ErrorCode.WORKER_ERROR) from None
    return to_read(run, assets)


@router.get("/runs/{run_id}/segments/{index}/content")
def segment_content(
    run_id: UUID, index: int, db: Db, tenant_id: Tenant,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    run, _ = service.get_run_payload(db, tenant_id, run_id)
    if (run.output_manifest or {}).get("media_retention"):
        raise ApiError(404, ErrorCode.PRODUCTION_ASSET_NOT_FOUND)
    segments = (run.output_manifest or {}).get("segments", [])
    if not 0 <= index < len(segments):
        raise ApiError(404, ErrorCode.PRODUCTION_ASSET_NOT_FOUND)
    segment = segments[index]
    expected = f"LifeReel-Biography/generated/{tenant_id}/{run.id}/segment-{index}.mp4"
    if segment.get("status") != "completed" or segment.get("storage_key") != expected:
        raise ApiError(404, ErrorCode.PRODUCTION_ASSET_NOT_FOUND)
    redirect = media_redirect(expected, "video/mp4")
    if redirect is not None:
        return redirect
    return streamed_media(expected, "video/mp4", range_header)


@router.get("/runs/{run_id}/segments/{index}/review/{position}")
def review_frame(run_id: UUID, index: int, position: int, db: Db, tenant_id: Tenant):
    run, _ = service.get_run_payload(db, tenant_id, run_id)
    manifest = run.output_manifest or {}
    segments = manifest.get("segments", [])
    if manifest.get("media_retention") or not 0 <= index < len(segments):
        raise ApiError(404, ErrorCode.PRODUCTION_ASSET_NOT_FOUND)
    frames = segments[index].get("review_frames", [])
    frame = next((f for f in frames if f.get("position") == position), None)
    expected = f"LifeReel-Biography/generated/{tenant_id}/{run.id}/review/{index}-{position}.jpg"
    if not frame or frame.get("storage_key") != expected:
        raise ApiError(404, ErrorCode.PRODUCTION_ASSET_NOT_FOUND)
    return streamed_media(expected, "image/jpeg", None)


@router.post("/runs/{run_id}/continuation", response_model=ProductionRunRead)
def retry_original(run_id: UUID, db: Db, tenant_id: Tenant) -> ProductionRunRead:
    from lifereel_api.modules.jobs import service as jobs

    run, assets = service.get_run_payload(db, tenant_id, run_id)
    if not run.job_id:
        raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
    job = jobs.retry_job(db, tenant_id, run.job_id, resume_original=True)
    try:
        jobs.enqueue(job)
    except Exception:
        jobs.fail_job(db, tenant_id, job.id, "WORKER_ERROR", None)
        raise ApiError(503, ErrorCode.WORKER_ERROR) from None
    return to_read(run, assets)

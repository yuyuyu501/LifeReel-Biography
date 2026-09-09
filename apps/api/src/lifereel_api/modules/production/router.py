from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import get_db
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.evidence.storage import private_storage
from lifereel_api.modules.production import service
from lifereel_api.modules.production.models import GeneratedAsset
from lifereel_api.modules.production.schemas import (
    GeneratedAssetRead,
    ProductionRunRead,
    ProductionStart,
)

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
    }


def to_read(run, assets) -> ProductionRunRead:
    return ProductionRunRead.model_validate(run).model_copy(
        update={"assets": [GeneratedAssetRead.model_validate(item) for item in assets]}
    )


@router.post("/runs", response_model=ProductionRunRead, status_code=status.HTTP_201_CREATED)
def start(payload: ProductionStart, db: Db, tenant_id: Tenant) -> ProductionRunRead:
    run = service.start_production(db, tenant_id, payload)
    _, assets = service.get_run_payload(db, tenant_id, run.id)
    return to_read(run, assets)


@router.get("/runs", response_model=list[ProductionRunRead])
def runs(db: Db, tenant_id: Tenant) -> list[ProductionRunRead]:
    return [
        to_read(item, service.get_run_payload(db, tenant_id, item.id)[1])
        for item in service.list_runs(db, tenant_id)
    ]


@router.post("/runs/{run_id}/execute", response_model=ProductionRunRead)
def execute(run_id: UUID, db: Db, tenant_id: Tenant) -> ProductionRunRead:
    run = service.execute_run(db, tenant_id, run_id)
    _, assets = service.get_run_payload(db, tenant_id, run.id)
    return to_read(run, assets)


@router.get("/assets/{asset_id}/content")
def asset_content(asset_id: UUID, db: Db, tenant_id: Tenant) -> Response:
    asset = db.get(GeneratedAsset, asset_id)
    if asset is None or asset.tenant_id != tenant_id:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.PRODUCTION_ASSET_NOT_FOUND)
    return Response(content=private_storage().get(asset.storage_key), media_type=asset.mime_type)

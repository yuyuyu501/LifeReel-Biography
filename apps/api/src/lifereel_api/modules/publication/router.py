from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.evidence.storage import private_storage
from lifereel_api.modules.publication import service
from lifereel_api.modules.publication.schemas import (
    PublicationCreate,
    PublicationRead,
    PublicPublicationRead,
)

router = APIRouter(tags=["publication"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]


@router.post("/publications", response_model=PublicationRead, status_code=status.HTTP_201_CREATED)
def publish(payload: PublicationCreate, db: Db, tenant_id: Tenant) -> PublicationRead:
    return service.publish(db, tenant_id, payload)


@router.get("/publications", response_model=list[PublicationRead])
def publications(db: Db, tenant_id: Tenant) -> list[PublicationRead]:
    return service.list_publications(db, tenant_id)


@router.post("/publications/{publication_id}/withdraw", response_model=PublicationRead)
def withdraw(publication_id: UUID, db: Db, tenant_id: Tenant) -> PublicationRead:
    return service.withdraw(db, tenant_id, publication_id)


@router.get("/public/{access_token}", response_model=PublicPublicationRead)
def public_publication(access_token: str, db: Db) -> PublicPublicationRead:
    return service.public_lookup(db, access_token)


@router.get("/public/{access_token}/content")
def public_content(access_token: str, db: Db) -> Response:
    asset = service.public_asset(db, access_token)
    return Response(content=private_storage().get(asset.storage_key), media_type=asset.mime_type)

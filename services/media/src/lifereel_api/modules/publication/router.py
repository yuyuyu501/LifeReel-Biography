from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.publication import service
from lifereel_api.modules.publication.schemas import (
    PublicationCreate,
    PublicationRead,
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


@router.get("/public/{access_token}")
@router.get("/public/{access_token}/content")
def public_unavailable(access_token: str) -> Response:
    # A tombstone for old clients: never return metadata or bytes from a token.
    return Response(status_code=404, headers={"Cache-Control": "no-store"})

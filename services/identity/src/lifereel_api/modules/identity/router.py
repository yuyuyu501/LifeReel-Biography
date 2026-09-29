from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.identity import service
from lifereel_api.modules.identity.schemas import PersonCreate, PersonRead, PersonUpdate

router = APIRouter(prefix="/persons", tags=["persons"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]


@router.get("", response_model=list[PersonRead])
def persons(db: Db, tenant_id: Tenant) -> list[PersonRead]:
    return service.list_persons(db, tenant_id)


@router.post("", response_model=PersonRead, status_code=status.HTTP_201_CREATED)
def create_person(payload: PersonCreate, db: Db, tenant_id: Tenant) -> PersonRead:
    return service.create_person(db, tenant_id, payload)


@router.get("/{person_id}", response_model=PersonRead)
def person(person_id: UUID, db: Db, tenant_id: Tenant) -> PersonRead:
    return service.get_person(db, tenant_id, person_id)


@router.patch("/{person_id}", response_model=PersonRead)
def patch_person(person_id: UUID, payload: PersonUpdate, db: Db, tenant_id: Tenant) -> PersonRead:
    return service.update_person(db, tenant_id, person_id, payload)

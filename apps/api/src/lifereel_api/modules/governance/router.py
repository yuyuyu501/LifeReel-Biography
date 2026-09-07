from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.governance import service
from lifereel_api.modules.governance.schemas import AuditEventRead, ConsentCreate, ConsentRead

router = APIRouter(tags=["governance"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]


@router.post("/consents", response_model=ConsentRead, status_code=status.HTTP_201_CREATED)
def create_consent(payload: ConsentCreate, db: Db, tenant_id: Tenant) -> ConsentRead:
    return service.create_consent(db, tenant_id, payload)


@router.get("/consents", response_model=list[ConsentRead])
def consents(db: Db, tenant_id: Tenant, subject_id: UUID | None = None) -> list[ConsentRead]:
    return service.list_consents(db, tenant_id, subject_id)


@router.post("/consents/{consent_id}/revoke", response_model=ConsentRead)
def revoke(consent_id: UUID, db: Db, tenant_id: Tenant) -> ConsentRead:
    return service.revoke_consent(db, tenant_id, consent_id)


@router.get("/audit", response_model=list[AuditEventRead])
def audit_log(db: Db, tenant_id: Tenant) -> list[AuditEventRead]:
    return service.list_audit(db, tenant_id)

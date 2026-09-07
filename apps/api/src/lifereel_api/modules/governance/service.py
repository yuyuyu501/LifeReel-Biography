from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.governance.models import AuditEvent, ConsentGrant
from lifereel_api.modules.governance.schemas import ConsentCreate
from lifereel_api.modules.identity.models import Person

SCOPE_ORDER = {"private": 0, "family": 1, "friends": 2, "public": 3}


def audit(
    db: Session,
    tenant_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID | str,
    details: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            details=details or {},
            created_at=datetime.now(UTC),
        )
    )


def create_consent(db: Session, tenant_id: UUID, payload: ConsentCreate) -> ConsentGrant:
    person = db.scalar(
        select(Person).where(Person.id == payload.subject_id, Person.tenant_id == tenant_id)
    )
    if person is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.SUBJECT_NOT_FOUND)
    grant = ConsentGrant(tenant_id=tenant_id, **payload.model_dump())
    db.add(grant)
    db.flush()
    audit(db, tenant_id, "consent.granted", "consent", grant.id, payload.model_dump(mode="json"))
    db.commit()
    db.refresh(grant)
    return grant


def list_consents(db: Session, tenant_id: UUID, subject_id: UUID | None) -> list[ConsentGrant]:
    statement = select(ConsentGrant).where(ConsentGrant.tenant_id == tenant_id)
    if subject_id:
        statement = statement.where(ConsentGrant.subject_id == subject_id)
    return list(db.scalars(statement.order_by(ConsentGrant.created_at.desc())))


def revoke_consent(db: Session, tenant_id: UUID, consent_id: UUID) -> ConsentGrant:
    grant = db.scalar(
        select(ConsentGrant).where(
            ConsentGrant.id == consent_id, ConsentGrant.tenant_id == tenant_id
        )
    )
    if grant is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.CONSENT_NOT_FOUND)
    grant.status = "revoked"
    audit(db, tenant_id, "consent.revoked", "consent", grant.id)
    db.commit()
    db.refresh(grant)
    return grant


def has_consent(
    db: Session, tenant_id: UUID, subject_id: UUID, consent_type: str, audience: str
) -> bool:
    grants = list(
        db.scalars(
            select(ConsentGrant).where(
                ConsentGrant.tenant_id == tenant_id,
                ConsentGrant.subject_id == subject_id,
                ConsentGrant.consent_type == consent_type,
                ConsentGrant.status == "granted",
            )
        )
    )
    now = datetime.now(UTC)
    return any(
        (grant.expires_at is None or grant.expires_at >= now)
        and SCOPE_ORDER.get(grant.scope, -1) >= SCOPE_ORDER.get(audience, 99)
        for grant in grants
    )


def list_audit(db: Session, tenant_id: UUID) -> list[AuditEvent]:
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(200)
        )
    )

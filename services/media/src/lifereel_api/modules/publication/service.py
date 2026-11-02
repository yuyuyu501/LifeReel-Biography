from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.governance import service as governance
from lifereel_api.modules.production.models import GeneratedAsset
from lifereel_api.modules.publication.models import Publication
from lifereel_api.modules.publication.schemas import PublicationCreate


def publish(db: Session, tenant_id: UUID, payload: PublicationCreate) -> Publication:
    # Publication is deliberately disabled while the product is account-private.
    raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.PUBLICATION_UNAVAILABLE)


def list_publications(db: Session, tenant_id: UUID) -> list[Publication]:
    publications = list(
        db.scalars(
            select(Publication)
            .where(Publication.tenant_id == tenant_id)
            .order_by(Publication.created_at.desc())
        )
    )
    return publications


def withdraw(db: Session, tenant_id: UUID, publication_id: UUID) -> Publication:
    publication = db.scalar(
        select(Publication).where(
            Publication.id == publication_id, Publication.tenant_id == tenant_id
        )
    )
    if publication is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.PUBLICATION_NOT_FOUND)
    publication.status = "withdrawn"
    publication.withdrawn_at = datetime.now(UTC)
    governance.audit(db, tenant_id, "publication.withdrawn", "publication", publication.id)
    db.commit()
    db.refresh(publication)
    return publication


def public_lookup(db: Session, token: str) -> Publication:
    # Reject legacy tokens too, regardless of their saved audience or consent.
    raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.PUBLICATION_UNAVAILABLE)


def public_asset(db: Session, token: str) -> GeneratedAsset:
    raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.PUBLICATION_UNAVAILABLE)

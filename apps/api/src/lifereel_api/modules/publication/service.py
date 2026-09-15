from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.governance import service as governance
from lifereel_api.modules.production.models import GeneratedAsset, ProductionRun
from lifereel_api.modules.publication.models import Publication
from lifereel_api.modules.publication.schemas import PublicationCreate
from lifereel_api.modules.script.models import ScriptProject


def publish(db: Session, tenant_id: UUID, payload: PublicationCreate) -> Publication:
    run = db.scalar(
        select(ProductionRun).where(
            ProductionRun.id == payload.production_run_id,
            ProductionRun.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if (run is None or run.status != "completed"
            or (run.output_manifest or {}).get("media_retention")):
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.PRODUCTION_NOT_COMPLETED)
    if payload.audience != run.audience:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.PUBLICATION_AUDIENCE_MISMATCH)
    project = db.get(ScriptProject, run.project_id)
    if project is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.SCRIPT_PROJECT_NOT_FOUND)
    if payload.audience != "private" and not governance.has_consent(
        db, tenant_id, project.subject_id, "publication", payload.audience
    ):
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.PUBLICATION_CONSENT_REQUIRED)
    publication = Publication(
        tenant_id=tenant_id,
        production_run_id=run.id,
        subject_id=project.subject_id,
        audience=payload.audience,
        status="published",
        access_token=secrets.token_urlsafe(24),
        published_at=datetime.now(UTC),
    )
    db.add(publication)
    db.flush()
    governance.audit(
        db,
        tenant_id,
        "publication.published",
        "publication",
        publication.id,
        {"audience": payload.audience},
    )
    db.commit()
    db.refresh(publication)
    return publication


def list_publications(db: Session, tenant_id: UUID) -> list[Publication]:
    return list(
        db.scalars(
            select(Publication)
            .where(Publication.tenant_id == tenant_id)
            .order_by(Publication.created_at.desc())
        )
    )


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
    publication = db.scalar(
        select(Publication).where(
            Publication.access_token == token, Publication.status == "published"
        )
    )
    if publication is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.PUBLICATION_UNAVAILABLE)
    return publication


def public_asset(db: Session, token: str) -> GeneratedAsset:
    publication = public_lookup(db, token)
    asset = db.scalar(
        select(GeneratedAsset).where(
            GeneratedAsset.production_run_id == publication.production_run_id,
            GeneratedAsset.kind.in_(["final_video", "final_video_manifest"]),
        )
    )
    if asset is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.PUBLICATION_ASSET_UNAVAILABLE)
    return asset

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.auth.dependencies import AuthContext, auth_context
from lifereel_api.modules.interview import profile_export, profile_service
from lifereel_api.modules.interview.profile_schemas import ProfilePatch

router = APIRouter(prefix="/life-profiles", tags=["life-profiles"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]
Auth = Annotated[AuthContext, Depends(auth_context)]


@router.get("/subjects/{subject_id}")
def subject_profile(subject_id: UUID, db: Db, tenant: Tenant):
    profile = profile_service.ensure(db, tenant, subject_id)
    return profile_service.read(db, tenant, profile.id)


@router.get("/{profile_id}")
def read(profile_id: UUID, db: Db, tenant: Tenant):
    return profile_service.read(db, tenant, profile_id)


@router.patch("/{profile_id}")
def patch(profile_id: UUID, payload: ProfilePatch, db: Db, tenant: Tenant, auth: Auth):
    if not payload.changes:
        raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)
    return profile_service.patch(
        db, tenant, profile_id, payload, actor=f"manual:{auth.user_id or 'test'}"
    )


@router.get("/{profile_id}/history")
def history(profile_id: UUID, db: Db, tenant: Tenant):
    return profile_service.history(db, tenant, profile_id)


@router.get("/{profile_id}/export")
def export(
    profile_id: UUID,
    db: Db,
    tenant: Tenant,
    auth: Auth,
    format: Literal["md", "xlsx"] = "xlsx",
    include_private: bool = False,
    sections: Annotated[list[str] | None, Query()] = None,
):
    if include_private and auth.role == "viewer":
        raise ApiError(403, ErrorCode.AUTH_READ_ONLY)
    profile = profile_service.read(db, tenant, profile_id)
    valid = {s["key"] for s in profile["sections"]}
    if sections and not set(sections) <= valid:
        raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)
    content = (
        profile_export.xlsx(profile, include_private, sections)
        if format == "xlsx"
        else profile_export.markdown(profile, include_private, sections)
    )
    media_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if format == "xlsx"
        else "text/markdown; charset=utf-8"
    )
    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="life-profile-{profile_id}'
                f'-v{profile["version_number"]}.{format}"'
            ),
            "Cache-Control": "private, no-store",
        },
    )

"""Editable chapter media, shared by script previews and production snapshots."""

from uuid import UUID

from sqlalchemy import select

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.evidence.models import SourceAsset
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.modules.script.models import ScriptScene

IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
AUDIO_MIMES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav"}


def eligible(asset) -> bool:
    return bool(
        asset.status == "ready" and asset.consent_status == "granted"
        and not asset.is_redraw
        and (
            asset.kind == "photo" and asset.mime_type in IMAGE_MIMES
            and 0 < asset.byte_size <= 10 * 1024 * 1024
            or asset.kind == "audio" and asset.mime_type in AUDIO_MIMES
            and 0 < asset.byte_size <= 15 * 1024 * 1024
        )
    )


def validate_assets(db, tenant_id, subject_id, asset_ids):
    if len(set(asset_ids)) != len(asset_ids):
        raise ApiError(422, ErrorCode.VIDEO_REFERENCE_INVALID)
    assets = [db.get(SourceAsset, UUID(str(value))) for value in asset_ids]
    if any(
        not asset or asset.tenant_id != tenant_id or asset.subject_id != subject_id
        or not eligible(asset) for asset in assets
    ):
        raise ApiError(422, ErrorCode.VIDEO_REFERENCE_INVALID)
    if sum(a.kind == "photo" for a in assets) > 9 or sum(a.kind == "audio" for a in assets) > 3:
        raise ApiError(422, ErrorCode.VIDEO_REFERENCE_INVALID)
    return assets


def resolve(db, project, scene, *, strict=True):
    if scene.reference_asset_ids is not None:
        if not strict:
            assets = [db.get(SourceAsset, UUID(value)) for value in scene.reference_asset_ids]
            return [a for a in assets if a and a.tenant_id == project.tenant_id
                    and a.subject_id == project.subject_id]
        return validate_assets(db, project.tenant_id, project.subject_id, scene.reference_asset_ids)
    assets = list(db.scalars(select(SourceAsset).where(
        SourceAsset.tenant_id == project.tenant_id,
        SourceAsset.subject_id == project.subject_id,
        SourceAsset.chapter_id == scene.chapter_id,
    ).order_by(SourceAsset.quality_score.desc().nullslast(), SourceAsset.created_at.desc())))
    selected = []
    for asset in assets:
        if asset.is_restoration:
            continue
        duration = (asset.metadata_json or {}).get("duration_seconds")
        short_audio = isinstance(duration, (int, float)) and 2 <= duration <= 15
        if eligible(asset) and (asset.kind == "photo" or short_audio):
            selected.append(asset)
    # Existing chapters get their primary photo and audio without an extra user step.
    return [a for kind in ("photo", "audio") if (a := next(
        (item for item in selected if item.kind == kind), None,
    )) is not None]


def get_scene(db, tenant_id, project_id, scene_id):
    from lifereel_api.modules.script.service import get_project

    project, _, _ = get_project(db, tenant_id, project_id)
    scene = db.scalar(select(ScriptScene).where(
        ScriptScene.id == scene_id, ScriptScene.project_id == project.id,
        ScriptScene.tenant_id == tenant_id,
    ))
    if scene is None:
        raise ApiError(409, ErrorCode.SCRIPT_EDIT_CONFLICT)
    return project, scene


def update(db, tenant_id, project_id, scene_id, payload):
    from lifereel_api.modules.script.service import get_project

    project, scene = get_scene(db, tenant_id, project_id, scene_id)
    with execution_lock(db, project.subject_id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.SCRIPT_EDIT_BUSY)
        db.refresh(project)
        db.refresh(scene)
        if project.version_number != payload.expected_version:
            raise ApiError(409, ErrorCode.SCRIPT_EDIT_CONFLICT)
        validate_assets(db, tenant_id, project.subject_id, payload.asset_ids)
        scene.reference_asset_ids = [str(value) for value in payload.asset_ids]
        project.version_number += 1
        project.status = "draft"
        db.commit()
    return get_project(db, tenant_id, project_id)

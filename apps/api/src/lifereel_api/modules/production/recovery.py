"""Explicit replacement of rejected reference images, including legacy failed runs."""

import copy
from uuid import UUID

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.models import utcnow
from lifereel_api.modules.evidence.models import SourceAsset
from lifereel_api.modules.script.models import ScriptProject

REFERENCE_MIMES = {"image/jpeg", "image/png", "image/webp"}
MAX_REFERENCE_BYTES = 10 * 1024 * 1024


def moderation_code(provider_code: str | None) -> str | None:
    if not provider_code:
        return None
    if provider_code.startswith((
        "InputImageSensitiveContentDetected", "InputVideoSensitiveContentDetected",
    )):
        return ErrorCode.VIDEO_REFERENCE_REJECTED.value
    if "SensitiveContentDetected" in provider_code:
        return ErrorCode.VIDEO_CONTENT_REJECTED.value
    return None


def can_restore_original(run) -> bool:
    blocked = blocked_segment(run)
    if not blocked or run.status != "failed":
        return False
    index, segment, code = blocked
    return bool(
        index > 0 and code == ErrorCode.VIDEO_REFERENCE_REJECTED
        and not segment.get("task_id") and not segment.get("reference_kind")
        and not segment.get("original_restored") and not segment.get("reference_asset_id")
        and run.output_manifest["segments"][index - 1].get("status") == "completed"
    )


def restore_original(db, run) -> None:
    from lifereel_api.modules.evidence.storage import private_storage
    from lifereel_api.modules.governance.service import audit
    from lifereel_api.modules.production.continuation import prepare_original
    from lifereel_api.modules.production.providers import (
        VideoProviderError,
        VolcengineSeedanceProvider,
    )

    if not can_restore_original(run):
        raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
    index, _, _ = blocked_segment(run)
    manifest = copy.deepcopy(run.output_manifest)
    provider = VolcengineSeedanceProvider(options=manifest["generation_config"])
    try:
        _, _, source = prepare_original(
            provider, private_storage(), run, index - 1, manifest["segments"][index - 1],
        )
    except VideoProviderError as exc:
        raise ApiError(422, ErrorCode.VIDEO_CONTINUATION_UNAVAILABLE) from exc
    finally:
        provider.client.close()
    segment = manifest["segments"][index]
    segment.setdefault("reference_history", []).append({
        "replaced_at": utcnow().isoformat(), "source": source,
        "previous_provider_error_code": segment.get("provider_error_code"),
    })
    segment.update({
        "original_restored": True, "reference_kind": source["kind"],
        "reference_sha256": source["sha256"], "provider_error_code": None, "status": "pending",
    })
    run.output_manifest = manifest
    audit(db, run.tenant_id, "production.original_restored", "production_run", run.id, source)


def blocked_segment(run):
    segments = (run.output_manifest or {}).get("segments", [])
    for index, segment in enumerate(segments):
        if segment.get("status") != "completed":
            code = moderation_code(segment.get("provider_error_code"))
            return (index, segment, code) if code else None
    return None


def details(run) -> dict | None:
    blocked = blocked_segment(run)
    if run.status != "failed" or not blocked:
        return None
    index, segment, code = blocked
    rejected = segment.get("rejected_reference_asset_ids", [])
    current = segment.get("reference_asset_id")
    return {
        "code": code, "segment_index": index,
        "rejected_asset_ids": list(dict.fromkeys([*rejected, *([current] if current else [])])),
        "can_restore_original": can_restore_original(run),
    }


def assert_retry_allowed(run) -> None:
    blocked = blocked_segment(run)
    code = blocked[2] if blocked else run.error_message
    if code in {ErrorCode.VIDEO_REFERENCE_REJECTED, ErrorCode.VIDEO_CONTENT_REJECTED}:
        raise ApiError(409, ErrorCode(code))


def reference_asset(db, run, asset_id: UUID) -> SourceAsset:
    asset = db.get(SourceAsset, asset_id)
    project = db.get(ScriptProject, run.project_id)
    if (
        not asset or not project or asset.tenant_id != run.tenant_id
        or asset.subject_id != project.subject_id or asset.kind != "photo"
        or asset.status != "ready" or asset.mime_type not in REFERENCE_MIMES
        or not 0 < asset.byte_size <= MAX_REFERENCE_BYTES
    ):
        raise ApiError(422, ErrorCode.VIDEO_REFERENCE_INVALID)
    return asset


def replace_reference(db, run, asset_id: UUID) -> None:
    blocked = blocked_segment(run)
    if (
        run.status != "failed" or not blocked
        or blocked[2] != ErrorCode.VIDEO_REFERENCE_REJECTED
        or blocked[1].get("task_id")
    ):
        raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
    index, previous, _ = blocked
    asset = reference_asset(db, run, asset_id)
    rejected_hashes = previous.get("rejected_reference_hashes", [])
    rejected_ids = details(run)["rejected_asset_ids"]
    if (
        str(asset.id) in rejected_ids or asset.sha256 in rejected_hashes
        or asset.sha256 == previous.get("reference_sha256")
    ):
        raise ApiError(422, ErrorCode.VIDEO_REFERENCE_INVALID)
    manifest = copy.deepcopy(run.output_manifest)
    segment = manifest["segments"][index]
    segment.setdefault("reference_history", []).append({
        "replaced_at": utcnow().isoformat(), "source_asset_id": str(asset.id),
        "previous_provider_error_code": segment.get("provider_error_code"),
    })
    segment.update({
        "reference_asset_id": str(asset.id), "reference_sha256": asset.sha256,
        "rejected_reference_asset_ids": rejected_ids,
        "provider_error_code": None, "status": "pending",
    })
    run.output_manifest = manifest

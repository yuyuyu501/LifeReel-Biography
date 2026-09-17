"""Prepare the chapter's frozen references before normal video moderation."""

import base64
import copy
import hashlib
import json
import subprocess
from uuid import UUID

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.evidence import redraw
from lifereel_api.modules.evidence.models import SourceAsset
from lifereel_api.modules.evidence.storage import private_file, private_storage
from lifereel_api.modules.jobs import service as jobs
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.modules.script.models import ScriptProject
from lifereel_api.modules.script.references import validate_assets
from lifereel_api.providers import siliconflow


def audio_duration(asset):
    try:
        with private_file(asset.storage_key, asset.byte_size, ".audio") as path:
            result = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                "-of", "json", str(path),
            ], check=True, capture_output=True, timeout=30)
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
        if not 2 <= duration <= 15 or not any(
            stream.get("codec_type") == "audio" for stream in data.get("streams", [])
        ):
            raise ValueError("Invalid audio duration")
        return duration
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise ApiError(422, ErrorCode.VIDEO_AUDIO_REFERENCE_INVALID) from None


def source_assets(db, project, package):
    assets = validate_assets(db, project.tenant_id, project.subject_id, package["source_assets"])
    if any(a.sha256 != package["source_hashes"].get(str(a.id)) for a in assets):
        raise ApiError(422, ErrorCode.VIDEO_REFERENCE_INVALID)
    return assets


def validate_package(db, project, package, config):
    assets = source_assets(db, project, package)
    photos = [a for a in assets if a.kind == "photo"]
    audio = [a for a in assets if a.kind == "audio"]
    if audio and (not photos or not config.get("generate_audio")):
        raise ApiError(422, ErrorCode.VIDEO_AUDIO_REQUIRES_IMAGE)
    if sum(audio_duration(a) for a in audio) > 15.01:
        raise ApiError(422, ErrorCode.VIDEO_AUDIO_REFERENCE_INVALID)
    if photos and config.get("reference_style") == "color_redraw":
        settings = get_settings()
        if settings.photo_redraw_provider == "disabled" or (
            settings.photo_redraw_provider == "siliconflow" and not settings.siliconflow_api_key
        ):
            raise ApiError(503, ErrorCode.PHOTO_REDRAW_NOT_CONFIGURED)


def prepared_photo(db, run, source, record):
    asset = db.get(SourceAsset, UUID(record["asset_id"]))
    if (
        not asset or asset.tenant_id != run.tenant_id or asset.subject_id != source.subject_id
        or asset.status != "ready" or asset.consent_status != "granted" or not asset.is_redraw
        or asset.derived_from_asset_id != source.id
        or asset.metadata_json.get("source_sha256") != source.sha256
        or record.get("source_sha256") != source.sha256
    ):
        raise ApiError(422, ErrorCode.VIDEO_REFERENCE_INVALID)
    return asset


def authorize_retry(db, run):
    manifest = copy.deepcopy(run.output_manifest or {})
    package = manifest.get("reference_package", {})
    if package.get("schema") != 2 or (
        (manifest.get("generation_config") or {}).get("reference_style") != "color_redraw"
    ):
        return
    project = db.get(ScriptProject, run.project_id)
    retries = {}
    for source in source_assets(db, project, package):
        if source.kind != "photo":
            continue
        job = redraw.current_job(db, run.tenant_id, source.id)
        if job and job.status == "failed":
            if job.error_code == ErrorCode.PHOTO_REDRAW_REJECTED or job.attempt_count >= 3:
                raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
            retries[str(job.id)] = job.attempt_count
    # A user retry authorizes only the failed attempts observed at this point.
    manifest["redraw_retry_jobs"] = retries
    run.output_manifest = manifest


def prepare(db, run, manifest):
    package = manifest.get("reference_package", {})
    if package.get("schema") != 2:
        return True
    project = db.get(ScriptProject, run.project_id)
    assets = source_assets(db, project, package)
    config = manifest["generation_config"]
    if config.get("reference_style") != "color_redraw":
        return True
    if config.get("reference_prompt_version") != siliconflow.PROMPT_VERSION:
        raise ApiError(422, ErrorCode.PHOTO_REDRAW_SOURCE_INVALID)
    prepared = manifest.setdefault("prepared_references", {})
    for source in assets:
        if source.kind != "photo":
            continue
        key = str(source.id)
        if key in prepared:
            prepared_photo(db, run, source, prepared[key])
            continue
        manifest["stage"] = "preparing_references"
        run.output_manifest = copy.deepcopy(manifest)
        db.commit()
        job = redraw.create(db, run.tenant_id, source.id)
        with execution_lock(db, job.id) as acquired:
            if not acquired:
                return False
            db.refresh(job)
            if job.status == "failed":
                retries = manifest.get("redraw_retry_jobs", {})
                if retries.get(str(job.id)) != job.attempt_count:
                    raise ApiError(422, ErrorCode(job.error_code or "PHOTO_REDRAW_FAILED"))
                redraw.reset_failed_job(db, job)
                retries.pop(str(job.id))
                run.output_manifest = copy.deepcopy(manifest)
                db.commit()
            try:
                redraw.execute(db, job)
            except ApiError as exc:
                db.rollback()
                jobs.fail_job(db, run.tenant_id, job.id, exc.code.value, None)
                raise
        prepared[key] = {"asset_id": job.result["asset_id"], "source_sha256": source.sha256,
                         "prompt_version": siliconflow.PROMPT_VERSION}
        prepared_photo(db, run, source, prepared[key])
        run.output_manifest = copy.deepcopy(manifest)
        db.commit()
    return True


def media_url(asset):
    storage = private_storage()
    content = storage.get(asset.storage_key)
    if len(content) != asset.byte_size or hashlib.sha256(content).hexdigest() != asset.sha256:
        raise ApiError(422, ErrorCode.VIDEO_REFERENCE_INVALID)
    return storage.signed_url(asset.storage_key) or (
        f"data:{asset.mime_type};base64," + base64.b64encode(content).decode()
    )


def inputs(db, run, manifest):
    package = manifest["reference_package"]
    project = db.get(ScriptProject, run.project_id)
    assets = source_assets(db, project, package)
    photos, audio = [], []
    for source in assets:
        if source.kind == "photo":
            asset = source
            if manifest["generation_config"].get("reference_style") == "color_redraw":
                asset = prepared_photo(
                    db, run, source, manifest["prepared_references"][str(source.id)],
                )
            photos.append(media_url(asset))
        else:
            audio.append(media_url(source))
    return {"reference_images": photos, "reference_audio": audio}

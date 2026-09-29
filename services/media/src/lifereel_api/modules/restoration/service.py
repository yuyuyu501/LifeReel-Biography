import hashlib
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.evidence.models import SourceAsset
from lifereel_api.modules.evidence.storage import private_storage
from lifereel_api.modules.identity.models import Person
from lifereel_api.modules.jobs import service as jobs
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.modules.restoration.models import RestorationPhoto
from lifereel_api.modules.restoration.schemas import PhotoRead, RestorationRead
from lifereel_api.providers import seedream, siliconflow

KIND = "photo.restoration"
PROMPT_VERSION = "photo-restoration-v1"
BASE_PROMPT = (
    "修复这张老照片，以忠实保留原照片内容和人物身份特征为最高优先级。"
    "去除划痕、折痕、污渍及扫描噪点，适度改善轻微模糊、曝光和对比度。"
    "保留人物脸型、五官比例、年龄特征、表情、发型、服装、原有构图和照片尺寸比例，"
    "不美颜、不瘦脸、不幼态化，不转为插画或卡通，不添加文字。"
    "保留自然皮肤纹理和照片年代感。对无法辨认的区域谨慎处理，"
    "不要凭空增加人物、物体、面部特征或改写照片中的文字。"
)


def prompt(colorize):
    return BASE_PROMPT + (
        "为黑白或褪色照片添加自然克制的色彩，肤色自然，避免过饱和，不改变原有明暗关系。"
        if colorize
        else "黑白照片保持黑白，彩色照片保留原有色彩关系，适度修正褪色和偏色。"
    )


def selected_provider():
    settings = get_settings()
    if settings.photo_restoration_provider == "inherit":
        return settings.photo_redraw_provider
    return settings.photo_restoration_provider


def enabled(provider=None):
    settings = get_settings()
    provider = provider or selected_provider()
    return settings.job_queue_backend == "database" and (
        provider == "seedream" and bool(settings.volcengine_api_key)
        or provider == settings.photo_redraw_provider == "siliconflow"
        and bool(settings.siliconflow_api_key)
        or provider == settings.photo_redraw_provider == "mock"
        and settings.is_development
    )


def get_photo(db, tenant_id, photo_id):
    photo = db.get(RestorationPhoto, photo_id)
    if not photo or photo.tenant_id != tenant_id:
        raise ApiError(404, ErrorCode.PHOTO_RESTORATION_NOT_FOUND)
    return photo


def get_job(db, tenant_id, job_id):
    job = jobs.get_job(db, tenant_id, job_id)
    if job.kind != KIND:
        raise ApiError(404, ErrorCode.PHOTO_RESTORATION_NOT_FOUND)
    return job


async def upload(db, tenant_id, file):
    content = await file.read(siliconflow.MAX_BYTES + 1)
    if not content or len(content) > siliconflow.MAX_BYTES:
        raise ApiError(422, ErrorCode.PHOTO_RESTORATION_SOURCE_INVALID)
    mime = siliconflow.image_mime(content)
    if not mime:
        raise ApiError(422, ErrorCode.PHOTO_RESTORATION_SOURCE_INVALID)
    digest = hashlib.sha256(content).hexdigest()
    with execution_lock(db, tenant_id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.RESOURCE_BUSY)
        existing = db.scalar(
            select(RestorationPhoto).where(
                RestorationPhoto.tenant_id == tenant_id,
                RestorationPhoto.sha256 == digest,
            )
        )
        if existing:
            return existing
        extension = siliconflow.MIMES[mime]
        key = f"LifeReel-Biography/restoration/{tenant_id}/original/{digest}.{extension}"
        private_storage().put(key, content)
        photo = RestorationPhoto(
            tenant_id=tenant_id,
            original_filename=(file.filename or "photo")[:255],
            mime_type=mime,
            byte_size=len(content),
            sha256=digest,
            storage_key=key,
        )
        db.add(photo)
        db.commit()
        return photo


def start(db, tenant_id, payload):
    if not enabled():
        raise ApiError(503, ErrorCode.PHOTO_RESTORATION_NOT_CONFIGURED)
    photo = get_photo(db, tenant_id, payload.photo_id)
    text = prompt(payload.colorize)
    provider = selected_provider()
    model = seedream.MODEL if provider == "seedream" else siliconflow.MODEL
    parameters = {}
    if provider == "seedream":
        content = checked_content(photo.storage_key, photo.byte_size, photo.sha256)
        parameters = {"size": seedream.output_size(content), "image_count": 1}
    identity = f"{PROMPT_VERSION}:{model}:{provider}:{text}"
    if parameters:
        identity += f":{parameters['size']}:1"
    fingerprint = hashlib.sha256(identity.encode()).hexdigest()[:20]
    with execution_lock(db, photo.id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.RESOURCE_BUSY)
        job, _ = jobs.create_job(
            db,
            tenant_id,
            KIND,
            {
                "photo_id": str(photo.id),
                "source_sha256": photo.sha256,
                "colorize": payload.colorize,
                "prompt_version": PROMPT_VERSION,
                "prompt": text,
                "model": model,
                "provider": provider,
                **parameters,
            },
            f"restore:{photo.id}:{photo.sha256}:{fingerprint}",
        )
        db.commit()
        return job


def can_retry(job):
    return (
        job.status == "failed"
        and job.attempt_count < 3
        and job.error_code
        not in {
            ErrorCode.PHOTO_RESTORATION_REJECTED,
            ErrorCode.PHOTO_RESTORATION_SOURCE_INVALID,
        }
    )


def retry(db, job):
    with execution_lock(db, job.id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
        db.refresh(job)
        if not can_retry(job):
            raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
        get_photo(db, job.tenant_id, UUID(job.payload["photo_id"]))
        if not enabled() or not enabled(job.payload["provider"]):
            raise ApiError(503, ErrorCode.PHOTO_RESTORATION_NOT_CONFIGURED)
        job.status, job.error_code, job.error_message = "queued", None, None
        job.result = None
        job.lease_token, job.lease_expires_at = None, None
        db.commit()
        return job


def checked_content(key, size, digest):
    try:
        content = private_storage().get(key)
        if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Changed photo")
        return content
    except (OSError, ValueError):
        raise ApiError(422, ErrorCode.PHOTO_RESTORATION_SOURCE_INVALID) from None


def execute(db, job):
    if job.status == "completed":
        return
    if (job.result or {}).get("request_started"):
        raise ApiError(409, ErrorCode.PHOTO_RESTORATION_UNCERTAIN)
    provider = job.payload["provider"]
    if not enabled() or not enabled(provider):
        raise ApiError(503, ErrorCode.PHOTO_RESTORATION_NOT_CONFIGURED)
    photo = get_photo(db, job.tenant_id, UUID(job.payload["photo_id"]))
    model = seedream.MODEL if provider == "seedream" else siliconflow.MODEL
    if photo.sha256 != job.payload["source_sha256"] or job.payload["model"] != model:
        raise ApiError(422, ErrorCode.PHOTO_RESTORATION_SOURCE_INVALID)
    content = checked_content(photo.storage_key, photo.byte_size, photo.sha256)
    if provider == "seedream" and (
        job.payload.get("size") != seedream.output_size(content)
        or job.payload.get("image_count") != 1
    ):
        raise ApiError(422, ErrorCode.PHOTO_RESTORATION_SOURCE_INVALID)
    job.status = "running"
    job.attempt_count += 1
    job.result = {"request_started": True}
    db.commit()
    try:
        if provider == "seedream":
            result = seedream.edit(
                content, photo.mime_type, prompt=job.payload["prompt"], size=job.payload["size"],
            )
        else:
            result = siliconflow.edit(content, photo.mime_type, prompt=job.payload["prompt"])
    except ApiError as exc:
        mapped = exc.code.value.replace("PHOTO_REDRAW_", "PHOTO_RESTORATION_")
        raise ApiError(exc.status_code, ErrorCode(mapped)) from None
    if (
        not result.content
        or len(result.content) > siliconflow.MAX_BYTES
        or siliconflow.image_mime(result.content) != result.mime_type
    ):
        raise ApiError(502, ErrorCode.PHOTO_RESTORATION_RESULT_INVALID)
    digest = hashlib.sha256(result.content).hexdigest()
    extension = siliconflow.MIMES[result.mime_type]
    key = f"LifeReel-Biography/restoration/{job.tenant_id}/results/{job.id}/{digest}.{extension}"
    private_storage().put(key, result.content)
    job.result = {
        "storage_key": key,
        "mime_type": result.mime_type,
        "byte_size": len(result.content),
        "sha256": digest,
        "provider_trace_id": result.trace_id,
    }
    job.status, job.error_code, job.error_message = "completed", None, None
    db.commit()


def to_read(db, job):
    photo = get_photo(db, job.tenant_id, UUID(job.payload["photo_id"]))
    return RestorationRead(
        id=job.id,
        photo=PhotoRead.model_validate(photo),
        status=job.status,
        colorize=job.payload["colorize"],
        error_code=job.error_code,
        can_retry=can_retry(job),
        created_at=job.created_at,
    )


def history(db, tenant_id, page):
    query = select(Job).where(Job.tenant_id == tenant_id, Job.kind == KIND)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(Job.created_at.desc(), Job.id).offset((page - 1) * 12).limit(12)
    )
    return {
        "items": [to_read(db, job) for job in rows],
        "total": total,
        "page": page,
        "page_size": 12,
    }


def output(job):
    if job.status != "completed" or not job.result:
        raise ApiError(409, ErrorCode.PHOTO_RESTORATION_NOT_READY)
    return job.result


def filename(photo, job):
    suffix = "修复上色" if job.payload["colorize"] else "修复"
    extension = siliconflow.MIMES[output(job)["mime_type"]]
    return f"{Path(photo.original_filename).stem[:200]}-{suffix}.{extension}"


def save_to_person(db, tenant_id, job_id, subject_id):
    job = get_job(db, tenant_id, job_id)
    result = output(job)
    person = db.get(Person, subject_id)
    if not person or person.tenant_id != tenant_id:
        raise ApiError(404, ErrorCode.PERSON_NOT_FOUND)
    with execution_lock(db, subject_id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.RESOURCE_BUSY)
        existing = db.scalar(
            select(SourceAsset).where(
                SourceAsset.tenant_id == tenant_id,
                SourceAsset.subject_id == subject_id,
                SourceAsset.sha256 == result["sha256"],
            )
        )
        if existing:
            return existing
        photo = get_photo(db, tenant_id, UUID(job.payload["photo_id"]))
        content = checked_content(result["storage_key"], result["byte_size"], result["sha256"])
        asset_id = uuid4()
        key = f"LifeReel-Biography/tenants/{tenant_id}/persons/{subject_id}/restoration/{asset_id}"
        key += "." + siliconflow.MIMES[result["mime_type"]]
        private_storage().put(key, content)
        asset = SourceAsset(
            id=asset_id,
            tenant_id=tenant_id,
            subject_id=subject_id,
            kind="photo",
            status="ready",
            original_filename=filename(photo, job),
            mime_type=result["mime_type"],
            byte_size=result["byte_size"],
            sha256=result["sha256"],
            storage_key=key,
            consent_scope="private",
            consent_status="granted",
            analysis_status="not_applicable",
            metadata_json={
                "purpose": "photo_restoration",
                "synthetic": True,
                "restoration_job_id": str(job.id),
                "source_photo_id": str(photo.id),
                "source_sha256": photo.sha256,
                "colorize": job.payload["colorize"],
                "prompt_version": job.payload["prompt_version"],
            },
        )
        db.add(asset)
        db.commit()
        return asset

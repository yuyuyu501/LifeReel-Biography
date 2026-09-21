from __future__ import annotations

import codecs
import hashlib
import mimetypes
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifereel_api.core.capacity import limited
from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.processing_limits import require_memory_input
from lifereel_api.modules.billing.usage import track_usage
from lifereel_api.modules.evidence.asset_conflicts import is_asset_duplicate
from lifereel_api.modules.evidence.documents import extract_document
from lifereel_api.modules.evidence.models import (
    EvidenceObservation,
    SourceAsset,
    Transcript,
    TranscriptSegment,
    TranscriptVersion,
)
from lifereel_api.modules.evidence.schemas import TranscriptCreate, TranscriptRevisionCreate
from lifereel_api.modules.evidence.storage import private_file, private_storage
from lifereel_api.modules.identity.models import Person
from lifereel_api.modules.interview.models import InterviewSession
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient
from lifereel_api.providers.whisper import FasterWhisperClient

READ_CHUNK_BYTES = 1024 * 1024


def evidence_kind_for_mime(mime_type: str) -> str | None:
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type.startswith("image/"):
        return "photo"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type in {"application/pdf", "text/plain", "text/markdown"}:
        return "document"
    return None


def evidence_limit_bytes(kind: str) -> int:
    settings = get_settings()
    return {
        "photo": settings.max_evidence_image_bytes,
        "document": settings.max_evidence_document_bytes,
        "audio": settings.max_evidence_audio_bytes,
        "video": settings.max_evidence_video_bytes,
    }[kind]


def sniff_evidence_kind(header: bytes, declared_kind: str) -> str | None:
    if header.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")):
        return "photo"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "photo"
    if header.startswith(b"%PDF-"):
        return "document"
    if header.startswith((b"ID3", b"OggS", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
        return "audio"
    if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return "audio"
    if header.startswith(b"RIFF") and header[8:12] == b"AVI ":
        return "video"
    if header.startswith(b"\x1aE\xdf\xa3"):
        return declared_kind if declared_kind in {"audio", "video"} else None
    if len(header) >= 12 and header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"avif"}:
            return "photo"
        return declared_kind if declared_kind in {"audio", "video"} else None
    if declared_kind == "document" and b"\x00" not in header:
        try:
            codecs.getincrementaldecoder("utf-8-sig")().decode(header, final=False)
            return "document"
        except UnicodeDecodeError:
            return None
    return None


async def hash_upload(upload: UploadFile, limit_bytes: int, kind: str) -> tuple[str, int, bytes]:
    digest = hashlib.sha256()
    byte_size = 0
    header = b""
    while chunk := await upload.read(READ_CHUNK_BYTES):
        if not header:
            header = chunk[:64]
        byte_size += len(chunk)
        if byte_size > limit_bytes:
            raise ApiError(
                status.HTTP_413_CONTENT_TOO_LARGE,
                ErrorCode.EVIDENCE_FILE_TOO_LARGE,
                {"kind": kind, "limit_bytes": limit_bytes},
            )
        digest.update(chunk)
    await upload.seek(0)
    return digest.hexdigest(), byte_size, header


async def create_asset(
    db: Session,
    tenant_id: UUID,
    subject_id: UUID,
    interview_session_id: UUID | None,
    kind: str,
    consent_scope: str,
    upload: UploadFile,
) -> SourceAsset:
    subject = db.scalar(
        select(Person).where(Person.id == subject_id, Person.tenant_id == tenant_id)
    )
    if subject is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.SUBJECT_NOT_FOUND)
    if interview_session_id:
        session = db.scalar(
            select(InterviewSession).where(
                InterviewSession.id == interview_session_id,
                InterviewSession.subject_id == subject_id,
                InterviewSession.tenant_id == tenant_id,
            )
        )
        if session is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.INTERVIEW_NOT_FOUND)
        chapter_id = session.chapter_id
    else:
        chapter_id = None

    mime_type = upload.content_type or "application/octet-stream"
    if mime_type == "application/octet-stream":
        mime_type = mimetypes.guess_type(upload.filename or "")[0] or mime_type
    detected_kind = evidence_kind_for_mime(mime_type)
    if detected_kind is None or detected_kind != kind:
        raise ApiError(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, ErrorCode.EVIDENCE_TYPE_UNSUPPORTED)
    digest, byte_size, header = await hash_upload(
        upload, evidence_limit_bytes(detected_kind), detected_kind
    )
    if byte_size == 0:
        raise ApiError(status.HTTP_400_BAD_REQUEST, ErrorCode.EVIDENCE_FILE_EMPTY)
    if sniff_evidence_kind(header, detected_kind) != detected_kind:
        raise ApiError(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            ErrorCode.EVIDENCE_TYPE_UNSUPPORTED,
        )
    existing_query = select(SourceAsset).where(
        SourceAsset.tenant_id == tenant_id,
        SourceAsset.subject_id == subject_id,
        SourceAsset.sha256 == digest,
    )
    existing = db.scalar(existing_query)
    if existing:
        return existing

    safe_suffix = Path(upload.filename or "evidence.bin").suffix.lower()[:12]
    scope = f"chapters/{chapter_id}" if chapter_id else "profile"
    storage_key = (
        f"LifeReel-Biography/tenants/{tenant_id}/persons/{subject_id}/"
        f"{scope}/assets/{digest}/original{safe_suffix}"
    )
    asset = SourceAsset(
        tenant_id=tenant_id,
        subject_id=subject_id,
        interview_session_id=interview_session_id,
        chapter_id=chapter_id,
        kind=kind,
        original_filename=Path(upload.filename or "evidence.bin").name,
        mime_type=mime_type,
        byte_size=byte_size,
        sha256=digest,
        storage_key=storage_key,
        consent_scope=consent_scope,
        consent_status="granted",
        status="ready",
    )
    # begin_nested() flushes any caller changes first; keep that outside the
    # duplicate handler so an unrelated pending write cannot become a success.
    savepoint = db.begin_nested()
    try:
        with savepoint:
            db.add(asset)
            # Claim the unique identity before touching storage. Concurrent
            # inserts wait for commit/rollback, including uploads to other
            # chapters or with different suffixes (neither is part of dedup).
            db.flush()
            private_storage().put_file(storage_key, upload.file)
    except IntegrityError as exc:
        if not is_asset_duplicate(exc):
            raise
        # The savepoint has rolled back, so PostgreSQL READ COMMITTED can now
        # read the winning transaction without discarding the caller's changes.
        existing = db.scalar(existing_query)
        if existing is None:
            raise
        return existing
    try:
        db.commit()
    except Exception:
        db.rollback()
        # Object keys are shared with direct uploads. Never delete here: even
        # a failed/uncertain commit may leave an object another writer needs.
        raise
    db.refresh(asset)
    return asset


def list_assets(db: Session, tenant_id: UUID, subject_id: UUID | None) -> list[SourceAsset]:
    statement = select(SourceAsset).where(SourceAsset.tenant_id == tenant_id)
    if subject_id:
        statement = statement.where(SourceAsset.subject_id == subject_id)
    return list(db.scalars(statement.order_by(SourceAsset.created_at.desc())))


def get_asset(db: Session, tenant_id: UUID, asset_id: UUID) -> SourceAsset:
    asset = db.scalar(
        select(SourceAsset).where(SourceAsset.id == asset_id, SourceAsset.tenant_id == tenant_id)
    )
    if asset is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.EVIDENCE_ASSET_NOT_FOUND)
    return asset


@limited("transcription")
def transcribe_asset(db: Session, tenant_id: UUID, asset_id: UUID) -> Transcript:
    asset = get_asset(db, tenant_id, asset_id)
    if asset.kind not in {"audio", "video"}:
        raise ApiError(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            ErrorCode.EVIDENCE_ANALYSIS_UNSUPPORTED,
        )
    existing = db.scalar(
        select(Transcript).where(
            Transcript.source_asset_id == asset.id,
            Transcript.tenant_id == tenant_id,
        )
    )
    latest_existing = _latest_transcript_version(db, tenant_id, asset.id) if existing else None
    if latest_existing and latest_existing.source == "provider_asr":
        return existing
    settings = get_settings()
    if settings.asr_provider == "mock":
        mock_text = (
            f"【模拟转写】当前为开发演示模式，请在这里填写并校对“{asset.original_filename}”"
            "的实际内容。"
        )
        return create_transcript(
            db,
            tenant_id,
            asset.id,
            TranscriptCreate(text=mock_text, language="zh-CN", source="mock_asr"),
        )
    if settings.asr_provider not in {"openai-compatible", "faster-whisper"}:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, ErrorCode.ASR_NOT_CONFIGURED)
    if settings.asr_provider == "faster-whisper":
        subject = db.scalar(
            select(Person).where(Person.id == asset.subject_id, Person.tenant_id == tenant_id)
        )
        terms: list[str] = []
        if subject is not None:
            # Only explicit profile fields, never generated biographies/entities or ASR guesses.
            for value in (subject.display_name, subject.preferred_name, subject.birthplace):
                term = " ".join((value or "").split())
                if term and len(term) <= 64 and term not in terms:
                    terms.append(term)
        # A small vocabulary biases decoding without supplying a narrative to copy.
        bounded_terms: list[str] = []
        for term in terms:
            if len("、".join([*bounded_terms, term])) <= 160:
                bounded_terms.append(term)
        client = FasterWhisperClient(
            settings.asr_runtime_model,
            settings.whisper_device,
            settings.whisper_compute_type,
            hotwords="、".join(bounded_terms) or None,
        )
    else:
        client = OpenAICompatibleClient(
            settings.openai_compatible_base_url or "",
            settings.openai_compatible_api_key or "",
            settings.model_for("asr"),
        )
    if not client.capabilities().configured:
        raise ApiError(status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.ASR_CONFIGURATION_INCOMPLETE)
    try:
        if settings.asr_provider == "faster-whisper":
            with private_file(
                asset.storage_key, asset.byte_size, Path(asset.original_filename).suffix.lower()
            ) as source:
                text = client.transcribe(asset.original_filename, source, asset.mime_type).strip()
        else:
            text = client.transcribe(
                asset.original_filename,
                private_storage().get(asset.storage_key),
                asset.mime_type,
            ).strip()
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.ASR_REQUEST_FAILED) from exc
    if not text:
        raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.ASR_EMPTY_TRANSCRIPT)
    if existing:
        return append_transcript_version(
            db,
            tenant_id,
            existing,
            text,
            "provider_asr",
            "重新执行语音识别",
        )
    return create_transcript(
        db,
        tenant_id,
        asset.id,
        TranscriptCreate(text=text, language="zh-CN", source="provider_asr"),
    )


def _latest_transcript_version(
    db: Session, tenant_id: UUID, asset_id: UUID
) -> TranscriptVersion | None:
    return db.scalar(
        select(TranscriptVersion)
        .join(Transcript, Transcript.id == TranscriptVersion.transcript_id)
        .where(
            Transcript.tenant_id == tenant_id,
            Transcript.source_asset_id == asset_id,
        )
        .order_by(TranscriptVersion.version_number.desc())
    )


def _document_text(asset: SourceAsset, content: bytes | Path) -> str:
    return extract_document(content, asset.mime_type, str(asset.id))


@limited("decode")
def _video_frames(content: bytes | Path, suffix: str) -> list[tuple[str, bytes]]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return []
    with tempfile.TemporaryDirectory(prefix="lifereel-observe-") as temp_dir:
        source = (
            content if isinstance(content, Path) else Path(temp_dir) / f"source{suffix or '.mp4'}"
        )
        if isinstance(content, bytes):
            source.write_bytes(content)
        output_pattern = str(Path(temp_dir) / "frame-%02d.jpg")
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-threads",
                "2",
                "-filter_threads",
                "1",
                "-i",
                str(source),
                "-vf",
                "fps=1/10,scale=960:-2",
                "-frames:v",
                "4",
                output_pattern,
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        frame_paths = sorted(Path(temp_dir).glob("frame-*.jpg"))
        return [("image/jpeg", path.read_bytes()) for path in frame_paths]


def list_observations(db: Session, tenant_id: UUID, asset_id: UUID) -> list[EvidenceObservation]:
    get_asset(db, tenant_id, asset_id)
    return list(
        db.scalars(
            select(EvidenceObservation)
            .where(
                EvidenceObservation.tenant_id == tenant_id,
                EvidenceObservation.source_asset_id == asset_id,
            )
            .order_by(EvidenceObservation.version_number.desc())
        )
    )


@track_usage("evidence")
def analyze_asset(db: Session, tenant_id: UUID, asset_id: UUID) -> EvidenceObservation:
    asset = get_asset(db, tenant_id, asset_id)
    if asset.is_redraw or asset.is_restoration:
        raise ApiError(422, ErrorCode.EVIDENCE_ANALYSIS_UNSUPPORTED)
    settings = get_settings()
    content = (
        private_storage().get(asset.storage_key) if asset.kind == "photo" else b""
    )
    transcript_version: TranscriptVersion | None = None
    provider = "local"
    model_name: str | None = None
    confidence = 0.9

    try:
        if asset.kind in {"audio", "video"}:
            transcribe_asset(db, tenant_id, asset.id)
            transcript_version = _latest_transcript_version(db, tenant_id, asset.id)
            transcript_text = transcript_version.text if transcript_version else ""
            # Preserve the raw transcript/version, but do not promote oversized
            # text to an observation/round that every later compile will revisit.
            require_memory_input(transcript_text, source_asset_id=str(asset.id))
            text = transcript_text
            analysis_kind = "transcript" if asset.kind == "audio" else "multimodal_description"
            if transcript_version and transcript_version.source == "mock_asr":
                provider = "mock"
                confidence = 0.0
            elif transcript_version and transcript_version.source == "manual":
                provider = "manual"
            else:
                provider = settings.asr_provider if transcript_version else "local"
                model_name = settings.model_for("asr") or None

            if asset.kind == "video" and settings.llm_provider == "openai-compatible":
                vision_model = settings.model_for("vision")
                client = OpenAICompatibleClient(
                    settings.openai_compatible_base_url or "",
                    settings.openai_compatible_api_key or "",
                    vision_model,
                )
                suffix = Path(asset.original_filename).suffix.lower()
                with private_file(asset.storage_key, asset.byte_size, suffix) as source:
                    frames = _video_frames(source, suffix)
                if not client.capabilities().configured:
                    raise ApiError(
                        status.HTTP_503_SERVICE_UNAVAILABLE,
                        ErrorCode.VISION_CONFIGURATION_INCOMPLETE,
                    )
                if not frames:
                    raise ApiError(
                        status.HTTP_502_BAD_GATEWAY,
                        ErrorCode.VISION_RESPONSE_INVALID,
                    )
                try:
                    visual_text = client.analyze_images(
                        "你是口述史素材整理员。只描述画面中可见的客观信息，"
                        "不猜测身份、关系或年代。",
                        "请按时间顺序概括这些视频关键帧，并指出不确定之处。",
                        frames,
                    ).strip()
                except ApiError:
                    raise
                except Exception as exc:
                    raise ApiError(
                        status.HTTP_502_BAD_GATEWAY,
                        ErrorCode.VISION_REQUEST_FAILED,
                    ) from exc
                if not visual_text:
                    raise ApiError(
                        status.HTTP_502_BAD_GATEWAY,
                        ErrorCode.VISION_RESPONSE_INVALID,
                    )
                text = (f"音频逐字稿：\n{transcript_text}\n\n画面观察：\n{visual_text}").strip()
                provider = "openai-compatible"
                model_name = vision_model
            elif asset.kind == "video" and settings.llm_provider != "mock":
                raise ApiError(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    ErrorCode.VISION_CONFIGURATION_INCOMPLETE,
                )
        elif asset.kind == "document":
            with private_file(
                asset.storage_key, asset.byte_size, Path(asset.original_filename).suffix.lower()
            ) as source:
                text = _document_text(asset, source)
            analysis_kind = "document_text"
            if not text:
                raise ValueError("DOCUMENT_TEXT_EMPTY")
        elif asset.kind == "photo":
            vision_model = settings.model_for("vision")
            client = OpenAICompatibleClient(
                settings.openai_compatible_base_url or "",
                settings.openai_compatible_api_key or "",
                vision_model,
            )
            if settings.llm_provider == "mock":
                text = f"【待分析图片】{asset.original_filename}"
                provider = "mock"
                confidence = 0.0
            elif (
                settings.llm_provider != "openai-compatible" or not client.capabilities().configured
            ):
                raise ApiError(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    ErrorCode.VISION_CONFIGURATION_INCOMPLETE,
                )
            else:
                try:
                    text = client.analyze_images(
                        "你是口述史素材整理员。只描述可见事实，不猜测人物身份、关系、地点或年代。",
                        "请描述这张图片中的人物、环境、物品、文字线索与不确定信息。",
                        [(asset.mime_type, content)],
                    ).strip()
                except ApiError:
                    raise
                except Exception as exc:
                    raise ApiError(
                        status.HTTP_502_BAD_GATEWAY,
                        ErrorCode.VISION_REQUEST_FAILED,
                    ) from exc
                if not text:
                    raise ApiError(
                        status.HTTP_502_BAD_GATEWAY,
                        ErrorCode.VISION_RESPONSE_INVALID,
                    )
                provider = "openai-compatible"
                model_name = vision_model
            analysis_kind = "visual_description"
        else:
            raise ApiError(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                ErrorCode.EVIDENCE_ANALYSIS_UNSUPPORTED,
            )
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.EVIDENCE_ANALYSIS_FAILED,
        ) from exc

    if not text.strip():
        raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.EVIDENCE_ANALYSIS_FAILED)
    # Includes combined video descriptions and documents whose configurable
    # extraction budget is larger than the downstream memory input contract.
    require_memory_input(text, source_asset_id=str(asset.id))
    latest_version = db.scalar(
        select(func.max(EvidenceObservation.version_number)).where(
            EvidenceObservation.tenant_id == tenant_id,
            EvidenceObservation.source_asset_id == asset.id,
        )
    )
    observation = EvidenceObservation(
        tenant_id=tenant_id,
        subject_id=asset.subject_id,
        source_asset_id=asset.id,
        source_transcript_version_id=transcript_version.id if transcript_version else None,
        version_number=(latest_version or 0) + 1,
        analysis_kind=analysis_kind,
        text=text.strip(),
        locator={
            "filename": asset.original_filename,
            **({"coverage": "full", "extracted_chars": len(text),
                "source_sha256": asset.sha256} if asset.kind == "document" else {}),
        },
        confidence=confidence,
        review_status="unreviewed",
        provider=provider,
        model_name=model_name,
    )
    db.add(observation)
    asset.analysis_status = "analyzed"
    asset.quality_score = max(0.0, min(1.0, confidence))
    if asset.kind in {"audio", "video"}:
        asset.voice_score = asset.quality_score
    if asset.kind in {"photo", "video"}:
        asset.identity_score = asset.quality_score
    asset.metadata_json = {
        **(asset.metadata_json or {}),
        "analysis_kind": analysis_kind,
        "last_observation_id": str(observation.id),
    }
    db.commit()
    db.refresh(observation)
    return observation


def create_transcript(
    db: Session, tenant_id: UUID, asset_id: UUID, payload: TranscriptCreate
) -> Transcript:
    get_asset(db, tenant_id, asset_id)
    existing = db.scalar(
        select(Transcript).where(
            Transcript.source_asset_id == asset_id, Transcript.tenant_id == tenant_id
        )
    )
    if existing:
        return existing
    transcript = Transcript(
        tenant_id=tenant_id,
        source_asset_id=asset_id,
        language=payload.language,
        status="ready",
        current_version=1,
    )
    db.add(transcript)
    db.flush()
    version = TranscriptVersion(
        tenant_id=tenant_id,
        transcript_id=transcript.id,
        version_number=1,
        text=payload.text,
        source=payload.source,
    )
    db.add(version)
    db.flush()
    db.add(
        TranscriptSegment(
            tenant_id=tenant_id,
            transcript_version_id=version.id,
            order_index=1,
            text=payload.text,
        )
    )
    db.commit()
    db.refresh(transcript)
    return transcript


def get_transcript_by_asset(db: Session, tenant_id: UUID, asset_id: UUID) -> Transcript:
    transcript = db.scalar(
        select(Transcript).where(
            Transcript.source_asset_id == asset_id,
            Transcript.tenant_id == tenant_id,
        )
    )
    if transcript is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.TRANSCRIPT_NOT_FOUND)
    return transcript


def revise_transcript(
    db: Session, tenant_id: UUID, transcript_id: UUID, payload: TranscriptRevisionCreate
) -> Transcript:
    transcript = db.scalar(
        select(Transcript).where(Transcript.id == transcript_id, Transcript.tenant_id == tenant_id)
    )
    if transcript is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.TRANSCRIPT_NOT_FOUND)
    return append_transcript_version(
        db, tenant_id, transcript, payload.text, "manual", payload.edit_reason
    )


def append_transcript_version(
    db: Session,
    tenant_id: UUID,
    transcript: Transcript,
    text: str,
    source: str,
    edit_reason: str | None,
) -> Transcript:
    next_version = (
        db.scalar(
            select(func.max(TranscriptVersion.version_number)).where(
                TranscriptVersion.transcript_id == transcript.id
            )
        )
        or 0
    ) + 1
    version = TranscriptVersion(
        tenant_id=tenant_id,
        transcript_id=transcript.id,
        version_number=next_version,
        text=text,
        source=source,
        edit_reason=edit_reason,
    )
    db.add(version)
    db.flush()
    db.add(
        TranscriptSegment(
            tenant_id=tenant_id,
            transcript_version_id=version.id,
            order_index=1,
            text=text,
        )
    )
    transcript.current_version = next_version
    db.commit()
    return transcript


def get_transcript_payload(
    db: Session, tenant_id: UUID, transcript_id: UUID
) -> tuple[Transcript, list[tuple[TranscriptVersion, list[TranscriptSegment]]]]:
    transcript = db.scalar(
        select(Transcript).where(Transcript.id == transcript_id, Transcript.tenant_id == tenant_id)
    )
    if transcript is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.TRANSCRIPT_NOT_FOUND)
    versions = list(
        db.scalars(
            select(TranscriptVersion)
            .where(TranscriptVersion.transcript_id == transcript.id)
            .order_by(TranscriptVersion.version_number)
        )
    )
    payload = []
    for version in versions:
        segments = list(
            db.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.transcript_version_id == version.id)
                .order_by(TranscriptSegment.order_index)
            )
        )
        payload.append((version, segments))
    return transcript, payload

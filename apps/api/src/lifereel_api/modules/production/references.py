"""Chapter-scoped, consent-aware reference selection for video production."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.modules.evidence.models import SourceAsset
from lifereel_api.modules.interview.models import Chapter
from lifereel_api.modules.production.models import ProductionRun
from lifereel_api.modules.production.recovery import reference_asset


def initial_photo_reference(db: Session, run: ProductionRun) -> SourceAsset | None:
    package = (run.output_manifest or {}).get("reference_package") or {}
    asset_id = package.get("character_reference")
    if not asset_id:
        return None
    asset = db.get(SourceAsset, UUID(asset_id))
    # Video references in older packages are not first-frame images.
    if asset is not None and asset.kind == "video":
        return None
    return reference_asset(db, run, UUID(asset_id))


def _age_match(asset: SourceAsset, chapter: Chapter | None) -> bool:
    if not chapter or chapter.age_start is None or asset.age_start is None:
        return True
    asset_end = asset.age_end if asset.age_end is not None else asset.age_start
    target_end = chapter.age_end if chapter.age_end is not None else chapter.age_start
    return asset.age_start <= target_end and asset_end >= chapter.age_start


def build_reference_package(
    db: Session,
    tenant_id: UUID,
    subject_id: UUID,
    chapter_id: UUID | None,
) -> dict:
    chapter = (
        db.scalar(select(Chapter).where(Chapter.id == chapter_id, Chapter.tenant_id == tenant_id))
        if chapter_id
        else None
    )
    assets = list(
        db.scalars(
            select(SourceAsset)
            .where(
                SourceAsset.tenant_id == tenant_id,
                SourceAsset.subject_id == subject_id,
                SourceAsset.status == "ready",
                SourceAsset.consent_status == "granted",
            )
            .order_by(SourceAsset.quality_score.desc().nullslast(), SourceAsset.created_at.desc())
        )
    )
    chapter_assets = [a for a in assets if a.chapter_id == chapter_id and _age_match(a, chapter)]
    fallback_assets = [a for a in assets if a.chapter_id != chapter_id and _age_match(a, chapter)]
    chosen = chapter_assets + fallback_assets

    def first(kind: str) -> SourceAsset | None:
        return next((a for a in chosen if a.kind == kind), None)

    photo = first("photo") or first("video")
    voice = first("audio") or first("video")
    video = first("video")
    source_assets = [a for a in (photo, voice, video) if a is not None]
    unique = {str(a.id): a for a in source_assets}
    return {
        "chapter_id": str(chapter_id) if chapter_id else None,
        "character_reference": str(photo.id) if photo else None,
        "character_reference_kind": photo.kind if photo else None,
        "voice_reference": str(voice.id) if voice else None,
        "scene_references": [str(video.id)] if video else [],
        "source_assets": [str(a.id) for a in unique.values()],
        "selection_reason": (
            "current_chapter"
            if chapter_assets
            else "same_person_other_chapter"
            if fallback_assets
            else "ai_generated_fallback"
        ),
        "age_target": {"start": chapter.age_start, "end": chapter.age_end} if chapter else None,
        "age_adaptation": {
            "image": "required" if photo and chapter and not _age_match(photo, chapter) else "none",
            "voice": "required" if voice and chapter and not _age_match(voice, chapter) else "none",
        },
        "consent_snapshot": "granted_only",
    }

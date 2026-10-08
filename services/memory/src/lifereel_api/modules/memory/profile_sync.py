import json
from uuid import UUID, uuid5

from sqlalchemy import delete, select

from lifereel_api.modules.interview.profile_models import LifeProfileEntry
from lifereel_api.modules.interview.profile_service import get, usable
from lifereel_api.modules.memory.models import MemoryClaim, MemoryConflict, TimelineAnchor


def sync(db, tenant, data):
    profile = get(db, tenant, UUID(data["profile_id"]), lock=True)
    rows = list(
        db.scalars(
            select(LifeProfileEntry).where(
                LifeProfileEntry.profile_id == profile.id,
                LifeProfileEntry.tenant_id == tenant,
            )
        )
    )
    current_ids = {r.id for r in rows}
    existing = list(
        db.scalars(
            select(MemoryClaim).where(
                MemoryClaim.tenant_id == tenant,
                MemoryClaim.subject_id == profile.subject_id,
                MemoryClaim.profile_entry_id.is_not(None),
            )
        )
    )
    changed_ids = set()
    for claim in existing:
        if claim.profile_entry_id not in current_ids:
            claim.review_status = "superseded"
            changed_ids.add(str(claim.id))
    active = []
    for row in rows:
        claim = next((c for c in existing if c.profile_entry_id == row.id), None)
        if claim is None:
            claim = MemoryClaim(
                id=uuid5(profile.id, f"entry:{row.id}"),
                tenant_id=tenant,
                subject_id=profile.subject_id,
                profile_entry_id=row.id,
                claim_type="profile",
                extraction_provider="life-profile",
                source_quote="",
                claim_text="",
                confidence=1.0,
            )
            db.add(claim)
        changed = claim.source_revision != row.version_number
        if changed:
            changed_ids.add(str(claim.id))
        claim.source_revision = row.version_number
        claim.claim_text = (
            row.value if isinstance(row.value, str) else json.dumps(row.value, ensure_ascii=False)
        )
        claim.source_quote = str(row.source.get("quote") or claim.claim_text)
        claim.fact_overrides = []
        claim.review_status = "verified" if row.certainty == "confirmed" else "unreviewed"
        if not usable(row):
            claim.review_status = "private" if row.use_scope == "internal" else "superseded"
        else:
            active.append(claim)
        source_id = row.source.get("supersedes_claim_id") or (
            row.source.get("id") if row.source.get("type") == "legacy_claim" else None
        )
        if source_id:
            old = db.scalar(
                select(MemoryClaim).where(
                    MemoryClaim.id == UUID(source_id),
                    MemoryClaim.tenant_id == tenant,
                    MemoryClaim.subject_id == profile.subject_id,
                )
            )
            if old and old.review_status != "superseded":
                old.review_status = "superseded"
                changed_ids.add(str(old.id))
    db.flush()
    if changed_ids:
        db.execute(
            delete(TimelineAnchor).where(
                TimelineAnchor.tenant_id == tenant,
                TimelineAnchor.claim_id.in_([UUID(i) for i in changed_ids]),
            )
        )
        for conflict in db.scalars(
            select(MemoryConflict).where(
                MemoryConflict.tenant_id == tenant,
                MemoryConflict.subject_id == profile.subject_id,
                MemoryConflict.status == "open",
            )
        ):
            if set(conflict.claim_ids) & changed_ids:
                conflict.status = "resolved"
    from lifereel_api.modules.memory.service import _compile_entities_and_timeline_rules

    _compile_entities_and_timeline_rules(db, tenant, active)
    db.commit()
    return {"profile_version": profile.version_number, "claim_count": len(active)}

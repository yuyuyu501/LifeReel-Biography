import hashlib
import json
from uuid import uuid4, uuid5

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.identity.models import Person
from lifereel_api.modules.interview.profile_models import (
    LifeProfile,
    LifeProfileEntry,
    LifeProfileRevision,
)
from lifereel_api.modules.interview.profile_schemas import ProfilePatch
from lifereel_api.modules.interview.profile_template import (
    FIELD_MAP,
    FIELDS,
    RULE_VERSION,
    SECTIONS,
    TEMPLATE_VERSION,
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def entry_data(row):
    return {
        "id": str(row.id),
        "field_key": row.field_key,
        "record_key": row.record_key,
        "value": row.value,
        "state": row.state,
        "certainty": row.certainty,
        "use_scope": row.use_scope,
        "source": row.source,
        "version_number": row.version_number,
        "pseudonyms": row.pseudonyms or {},
    }


def entries(db, profile):
    return list(
        db.scalars(
            select(LifeProfileEntry)
            .where(
                LifeProfileEntry.profile_id == profile.id,
                LifeProfileEntry.tenant_id == profile.tenant_id,
            )
            .order_by(LifeProfileEntry.field_key, LifeProfileEntry.created_at, LifeProfileEntry.id)
            .execution_options(populate_existing=True)
        )
    )


def get(db, tenant, profile_id, *, lock=False):
    stmt = select(LifeProfile).where(
        LifeProfile.id == profile_id,
        LifeProfile.tenant_id == tenant,
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    profile = db.scalar(stmt)
    if profile is None:
        raise ApiError(404, ErrorCode.PROFILE_NOT_FOUND)
    return profile


def ensure(db, tenant, subject_id):
    # Existing profiles are read without a person row lock. Other services may
    # already hold the foreign-key KEY SHARE lock while creating a work.
    existing = db.scalar(
        select(LifeProfile).where(
            LifeProfile.tenant_id == tenant, LifeProfile.subject_id == subject_id
        )
    )
    if existing is not None:
        return existing
    person = db.scalar(
        select(Person)
        .where(
            Person.id == subject_id,
            Person.tenant_id == tenant,
        )
        .with_for_update()
    )
    if person is None:
        raise ApiError(404, ErrorCode.SUBJECT_NOT_FOUND)
    profile = db.scalar(
        select(LifeProfile).where(
            LifeProfile.tenant_id == tenant,
            LifeProfile.subject_id == subject_id,
        )
    )
    if profile is not None:
        return profile
    profile = LifeProfile(
        tenant_id=tenant, subject_id=subject_id, template_version=TEMPLATE_VERSION, version_number=0
    )
    db.add(profile)
    db.flush()
    initial = {
        "identity.preferred_name": person.preferred_name or person.display_name,
        "scope.coverage": "截至目前的整个人生",
    }
    if person.birth_year:
        initial["identity.birth_time"] = str(person.birth_year)
    if person.birthplace:
        initial["identity.birth_place"] = person.birthplace
    for key, value in initial.items():
        db.add(
            LifeProfileEntry(
                tenant_id=tenant,
                profile_id=profile.id,
                field_key=key,
                record_key="single",
                value=value,
                state="filled",
                certainty="reported",
                use_scope="works",
                source={"type": "person", "id": str(person.id)},
                version_number=1,
            )
        )
    from lifereel_api.modules.memory.models import MemoryClaim

    for claim in db.scalars(
        select(MemoryClaim)
        .where(
            MemoryClaim.tenant_id == tenant,
            MemoryClaim.subject_id == subject_id,
            MemoryClaim.current_source(),
            MemoryClaim.review_status.not_in(["superseded", "disputed"]),
        )
        .order_by(MemoryClaim.created_at, MemoryClaim.id)
    ):
        db.add(
            LifeProfileEntry(
                id=uuid5(profile.id, f"legacy:{claim.id}"),
                tenant_id=tenant,
                profile_id=profile.id,
                field_key="legacy.events[]",
                record_key=str(claim.id),
                value={"title": "历史采访素材", "what": claim.current_text},
                state="filled",
                certainty="confirmed" if claim.review_status == "verified" else "pending",
                use_scope="internal" if claim.review_status == "private" else "works",
                source={
                    "type": "legacy_claim",
                    "id": str(claim.id),
                    "version": claim.source_revision,
                    "quote": claim.source_quote,
                },
                version_number=1,
            )
        )
    db.flush()
    changes = [{"before": None, "after": entry_data(row)} for row in entries(db, profile)]
    profile.version_number = 1
    db.add(
        LifeProfileRevision(
            tenant_id=tenant,
            profile_id=profile.id,
            version_number=1,
            request_id=uuid5(profile.id, "initial"),
            actor="migration",
            fingerprint=digest(changes),
            changes=changes,
        )
    )
    profile.readiness = evaluate(db, profile)
    db.commit()
    return profile


def usable(row):
    return (
        row.state == "filled"
        and row.certainty not in {"pending", "disputed"}
        and row.use_scope in {"works", "pseudonym"}
    )


def value_text(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def evaluate(db, profile):
    rows = entries(db, profile)
    available = [row for row in rows if usable(row)]
    themes = []
    for section in SECTIONS:
        candidates = [r for r in available if FIELD_MAP[r.field_key]["section"] == section["key"]]
        rich = []
        for row in candidates:
            value = row.value
            if isinstance(value, dict):
                what = str(value.get("what") or value.get("story") or "")
                action = str(value.get("action") or "")
                impact = str(value.get("impact") or value.get("result") or "")
                if len(what) >= 40 and len(action) >= 8 and len(impact) >= 8:
                    rich.append(row)
        if rich:
            themes.append(
                {
                    "title": section["title"],
                    "section": section["key"],
                    "entry_ids": [str(r.id) for r in rich],
                    "reason": "已有具体经过、本人行动和结果或影响，可尝试写作",
                }
            )
    scope = next((r.value for r in rows if r.field_key == "scope.coverage"), "整个人生")
    scoped_sections = scope.get("sections", []) if isinstance(scope, dict) else []
    relevant_themes = [t for t in themes if not scoped_sections or t["section"] in scoped_sections]
    selected = scoped_sections or [s["key"] for s in SECTIONS if s["key"] not in {"A", "L"}]
    suppressed_sections = {
        FIELD_MAP[r.field_key]["section"]
        for r in rows
        if r.field_key.endswith(".applicability") and r.state in {"not_applicable", "declined"}
    }
    applicable = []
    for section_key in selected:
        if section_key not in suppressed_sections:
            applicable.append(section_key)
    complete = bool(relevant_themes) and set(applicable) <= {t["section"] for t in relevant_themes}
    state = "ready" if complete else "partial_ready" if relevant_themes else "not_ready"
    handled = {r.field_key for r in rows if r.state != "empty"}
    missing = [
        f for f in FIELDS if f["key"] not in handled and f["section"] not in suppressed_sections
    ]
    return {
        "status": state,
        "profile_version": profile.version_number,
        "rule_version": RULE_VERSION,
        "scope": scope,
        "processed_fields": len(handled),
        "total_fields": len(FIELDS),
        "usable_entries": len(available),
        "themes": relevant_themes,
        "missing_fields": [
            {
                "key": f["key"],
                "label": f["label"],
                "question": f["question"],
                "section": f["section"],
            }
            for f in missing
        ],
        "message": "当前范围的素材可以进入写书，也可以继续补充。"
        if state == "ready"
        else "部分经历可以进入写书，其他人生阶段仍可继续补充。"
        if state == "partial_ready"
        else "已有资料仍需补充具体经过、行动和影响，才能尝试写书。",
    }


def read(db, tenant, profile_id):
    profile = get(db, tenant, profile_id)
    return {
        "id": str(profile.id),
        "subject_id": str(profile.subject_id),
        "template_version": profile.template_version,
        "version_number": profile.version_number,
        "sections": SECTIONS,
        "fields": FIELDS,
        "entries": [entry_data(row) for row in entries(db, profile)],
        "readiness": evaluate(db, profile),
    }


def patch(db, tenant, profile_id, payload: ProfilePatch, *, actor="manual", source=None):
    profile = get(db, tenant, profile_id, lock=True)
    fingerprint = digest(payload.model_dump(mode="json"))
    prior = db.scalar(
        select(LifeProfileRevision).where(
            LifeProfileRevision.profile_id == profile.id,
            LifeProfileRevision.request_id == payload.request_id,
        )
    )
    if prior:
        if prior.fingerprint != fingerprint:
            raise ApiError(409, ErrorCode.PROFILE_REQUEST_CONFLICT)
        # Memory locks this same profile in its own database session.
        # Replaying an accepted request must release our lock before that RPC.
        db.commit()
        sync_memory(db, tenant, profile_id)
        return read(db, tenant, profile_id)
    if profile.version_number != payload.expected_version:
        raise ApiError(409, ErrorCode.PROFILE_EDIT_CONFLICT)
    current = entries(db, profile)
    changes = []
    seen = set()
    for change in payload.changes:
        key = (change.field_key, change.record_key)
        if key in seen:
            raise ApiError(422, ErrorCode.PROFILE_OUTPUT_INVALID)
        seen.add(key)
        row = next((r for r in current if (r.field_key, r.record_key) == key), None)
        if change.id and (row is None or row.id != change.id):
            raise ApiError(409, ErrorCode.PROFILE_EDIT_CONFLICT)
        before = entry_data(row) if row else None
        if change.delete:
            if row:
                row.value = ""
                row.state = "empty"
                row.certainty = "pending"
                row.version_number += 1
            else:
                raise ApiError(404, ErrorCode.PROFILE_NOT_FOUND)
            after = None
        else:
            if row is None:
                row = LifeProfileEntry(
                    id=uuid4(),
                    tenant_id=tenant,
                    profile_id=profile.id,
                    field_key=change.field_key,
                    record_key=change.record_key,
                )
                db.add(row)
            row.value, row.state = change.value, change.state
            row.certainty = (
                "confirmed"
                if actor.startswith("manual") and change.certainty in {"reported", "confirmed"}
                else change.certainty
            )
            row.use_scope = change.use_scope
            row.pseudonyms = change.pseudonyms
            legacy_id = (row.source or {}).get("supersedes_claim_id") or (
                (row.source or {}).get("id")
                if (row.source or {}).get("type") == "legacy_claim"
                else None
            )
            row.source = {
                k: v
                for k, v in (source or {"type": "manual", "actor": actor}).items()
                if k != "quotes"
            }
            if legacy_id:
                row.source = {**row.source, "supersedes_claim_id": legacy_id}
            if source and source.get("quotes"):
                row.source = {
                    **row.source,
                    "quote": source["quotes"].get(change.field_key + ":" + change.record_key, ""),
                }
            row.version_number = (before["version_number"] if before else 0) + 1
            after = entry_data(row)
        changes.append({"before": before, "after": after})
    profile.version_number += 1
    if source and source.get("next_question"):
        changes.append({"metadata": {"next_question": source["next_question"]}})
    db.add(
        LifeProfileRevision(
            tenant_id=tenant,
            profile_id=profile.id,
            version_number=profile.version_number,
            request_id=payload.request_id,
            actor=actor,
            fingerprint=fingerprint,
            changes=changes,
        )
    )
    db.flush()
    profile.readiness = evaluate(db, profile)
    enqueue_sync(db, tenant, profile)
    db.commit()
    sync_memory(db, tenant, profile.id)
    return read(db, tenant, profile_id)


def history(db, tenant, profile_id):
    profile = get(db, tenant, profile_id)
    return jsonable_encoder(
        list(
            db.scalars(
                select(LifeProfileRevision)
                .where(
                    LifeProfileRevision.profile_id == profile.id,
                    LifeProfileRevision.tenant_id == tenant,
                )
                .order_by(LifeProfileRevision.version_number.desc())
            )
        )
    )


def snapshot(db, tenant, profile_id, entry_ids=None):
    profile = get(db, tenant, profile_id)
    all_rows = entries(db, profile)
    selected = {str(i) for i in entry_ids} if entry_ids is not None else None
    if selected is not None and not selected <= {str(r.id) for r in all_rows}:
        raise ApiError(404, ErrorCode.PROFILE_NOT_FOUND)
    source_rows = [r for r in all_rows if usable(r) and (selected is None or str(r.id) in selected)]
    if selected and len(source_rows) != len(selected):
        raise ApiError(409, ErrorCode.PROFILE_USE_RESTRICTED)
    name = next((r.value for r in all_rows if r.field_key == "identity.preferred_name"), "讲述者")
    return {
        "profile_id": str(profile.id),
        "profile_version": profile.version_number,
        "subject_id": str(profile.subject_id),
        "subject_name": str(name),
        "entries": [entry_data(r) for r in source_rows],
    }


def anonymized(entry):
    if entry.get("use_scope") != "pseudonym":
        return entry
    aliases = entry.get("pseudonyms") or {}

    def replace(value):
        if isinstance(value, str):
            for original, alias in sorted(aliases.items(), key=lambda item: -len(item[0])):
                value = value.replace(original, alias)
            return value
        if isinstance(value, list):
            return [replace(v) for v in value]
        if isinstance(value, dict):
            return {k: replace(v) for k, v in value.items()}
        return value

    source = dict(entry["source"])
    for key in ["quote", "question", "next_question"]:
        if key in source:
            source[key] = replace(source[key])
    return {**entry, "value": replace(entry["value"]), "source": source, "pseudonyms": {}}


def sync_memory(db, tenant, profile_id):
    from lifereel_api.architecture.internal import call
    from lifereel_api.architecture.topology import is_remote

    if is_remote("memory"):
        return call("memory", "memory.profile-sync", tenant, {"profile_id": str(profile_id)})
    from lifereel_api.modules.memory.profile_sync import sync

    return sync(db, tenant, {"profile_id": str(profile_id)})


def enqueue_sync(db, tenant, profile):
    from lifereel_api.modules.jobs.events import OutboxEvent

    identity = uuid5(profile.id, f"profile-sync:{profile.version_number}")
    if db.get(OutboxEvent, identity) is None:
        db.add(
            OutboxEvent(
                id=identity,
                tenant_id=tenant,
                event_type="profile.sync.requested",
                aggregate_id=profile.id,
                idempotency_key=str(identity),
                payload={"profile_id": str(profile.id), "version": profile.version_number},
            )
        )

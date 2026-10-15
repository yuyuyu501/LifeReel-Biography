import json
from uuid import UUID

from sqlalchemy import select

from lifereel_api.architecture.internal import call
from lifereel_api.architecture.topology import is_remote
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.book.models import BookChapter


def profile_read(db, tenant, subject_id=None, profile_id=None):
    if is_remote("interview"):
        return call(
            "interview",
            "profile.read",
            tenant,
            {"subject_id": str(subject_id)} if subject_id else {"profile_id": str(profile_id)},
        )
    from lifereel_api.modules.interview import profile_service

    profile = profile_service.ensure(db, tenant, subject_id) if subject_id else None
    return profile_service.read(db, tenant, profile.id if profile else profile_id)


def usable(entry):
    return (
        entry["state"] == "filled"
        and entry["certainty"] not in {"pending", "disputed"}
        and entry["use_scope"] in {"works", "pseudonym"}
    )


def theme_entries(profile, section=None):
    sections = {field["key"]: field["section"] for field in profile["fields"]}
    return [
        entry["id"] for entry in profile["entries"]
        if usable(entry)
        and (
            sections.get(entry["field_key"]) == section if section else
            not entry["field_key"].startswith(("preferences.", "identity.", "scope."))
        )
    ]


def default_themes(profile):
    themes = profile["readiness"]["themes"]
    if not themes:
        themes = [{"title": "我的人生经历"}]
    return [
        {**theme, "entry_ids": theme_entries(profile, theme.get("section"))}
        for theme in themes
    ]


def selected_entries(book, chapter, profile):
    selected = list(chapter.source_entry_ids)
    # Version 1 is the untouched system directory. Saving the directory makes all
    # selections explicit (version >= 2); never expand an intentional selection.
    if book.directory_version == 1 and not chapter.archived:
        section = next(
            (s["key"] for s in profile["sections"] if s["title"] == chapter.title), None
        )
        if section or chapter.title == "我的人生经历":
            selected.extend(theme_entries(profile, section))
    return list(dict.fromkeys(selected))


def sync_defaults(db, tenant, book, profile):
    if book.directory_version != 1:
        return
    rows = list(db.scalars(select(BookChapter).where(
        BookChapter.book_id == book.id, BookChapter.tenant_id == tenant,
    )))
    from lifereel_api.modules.jobs.models import Job

    if any(
        row.latest_job_id and (job := db.get(Job, row.latest_job_id))
        and job.status in {"queued", "running"} for row in rows
    ):
        return
    known = {row.title for row in rows}
    order = max((row.order_index for row in rows), default=0)
    for theme in default_themes(profile):
        if theme["title"] in known:
            continue
        order += 1
        db.add(
            BookChapter(
                tenant_id=tenant,
                book_id=book.id,
                title=theme["title"],
                order_index=order,
                source_entry_ids=theme["entry_ids"],
            )
        )


def initialize(db, tenant, book, profile):
    book.profile_id = UUID(profile["id"])
    sync_defaults(db, tenant, book, profile)
    db.flush()


def source(db, book, chapter_id):
    chapter = db.scalar(
        select(BookChapter).where(
            BookChapter.book_id == book.id,
            BookChapter.tenant_id == book.tenant_id,
            (BookChapter.id == chapter_id) | (BookChapter.chapter_id == chapter_id),
        )
    )
    if chapter is None:
        raise ApiError(404, ErrorCode.BOOK_CHAPTER_NOT_FOUND)
    profile = profile_read(db, book.tenant_id, profile_id=book.profile_id)
    selected_ids = selected_entries(book, chapter, profile)
    selected = set(selected_ids)
    candidates = [e for e in profile["entries"] if e["id"] in selected]
    from lifereel_api.modules.interview.profile_service import anonymized

    allowed = [
        anonymized(e)
        for e in candidates
        if usable(e)
    ]
    allowed_ids = {e["id"] for e in allowed}
    return {
        "profile_id": profile["id"],
        "profile_version": profile["version_number"],
        "subject_name": next(
            (
                anonymized(e)["value"]
                for e in profile["entries"]
                if e["field_key"] == "identity.preferred_name" and e["use_scope"] != "internal"
            ),
            "讲述者",
        ),
        "chapter": chapter.title,
        "target_words": book.target_words,
        "selected_entry_ids": selected_ids,
        "restricted_entry_ids": sorted(selected - allowed_ids),
        "preferences": [
            anonymized(e)
            for e in profile["entries"]
            if e["field_key"].startswith("preferences.") and e["use_scope"] != "internal"
        ],
        "claims": [
            {
                "id": e["id"],
                "revision": e["version_number"],
                "field_key": e["field_key"],
                "text": e["value"]
                if isinstance(e["value"], str)
                else json.dumps(e["value"], ensure_ascii=False),
                "source_quote": e["source"].get("quote", ""),
                "certainty": e["certainty"],
                "use_scope": e["use_scope"],
            }
            for e in allowed
        ],
    }


def edit_directory(db, tenant, book_id, payload):
    from lifereel_api.modules.book import service
    from lifereel_api.modules.jobs.models import Job
    from lifereel_api.modules.production.locking import execution_lock

    book = service.get_book(db, tenant, book_id)
    with execution_lock(db, book.id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.BOOK_GENERATION_BUSY)
        db.refresh(book)
        if book.directory_version != payload.expected_version:
            raise ApiError(409, ErrorCode.BOOK_VERSION_CONFLICT)
        profile = profile_read(db, tenant, subject_id=book.subject_id)
        book.profile_id = UUID(profile["id"])
        known_ids = {e["id"] for e in profile["entries"]}
        rows = list(
            db.scalars(
                select(BookChapter).where(
                    BookChapter.book_id == book.id,
                    BookChapter.tenant_id == tenant,
                )
            )
        )
        seen = set()
        for index, item in enumerate(payload.chapters, 1):
            if not set(map(str, item.source_entry_ids)) <= known_ids:
                raise ApiError(404, ErrorCode.PROFILE_NOT_FOUND)
            row = next((r for r in rows if r.id == item.id), None) if item.id else None
            if item.id and row is None:
                raise ApiError(404, ErrorCode.BOOK_CHAPTER_NOT_FOUND)
            if item.id in seen:
                raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)
            if item.id:
                seen.add(item.id)
            if row is None:
                row = BookChapter(tenant_id=tenant, book_id=book.id)
                db.add(row)
                db.flush()
            job = db.get(Job, row.latest_job_id) if row.latest_job_id else None
            if job and job.status in service.ACTIVE:
                raise ApiError(409, ErrorCode.BOOK_GENERATION_BUSY)
            row.title, row.order_index, row.archived = item.title, index, False
            row.source_entry_ids = list(map(str, item.source_entry_ids))
            seen.add(row.id)
        for row in rows:
            if row.id not in seen:
                job = db.get(Job, row.latest_job_id) if row.latest_job_id else None
                if job and job.status in service.ACTIVE:
                    raise ApiError(409, ErrorCode.BOOK_GENERATION_BUSY)
                row.archived = True
        book.title = payload.title
        book.directory_version += 1
        db.commit()
        return service.read(db, tenant, book.id)

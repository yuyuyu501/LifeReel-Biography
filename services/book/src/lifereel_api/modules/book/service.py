"""Durable chapter drafts with immutable versions and current evidence guards."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import select

from lifereel_api.architecture.topology import distributed
from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing import service as billing
from lifereel_api.modules.billing.commands import enqueue_transition
from lifereel_api.modules.billing.usage import track_usage
from lifereel_api.modules.book import writing
from lifereel_api.modules.book.models import Book, BookChapter, BookRevision
from lifereel_api.modules.book.schemas import BookRead, ChapterRead, RevisionRead
from lifereel_api.modules.identity.models import Person
from lifereel_api.modules.interview.models import Chapter
from lifereel_api.modules.jobs import service as jobs
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.memory.facts import fact_evidence
from lifereel_api.modules.memory.models import MemoryClaim, MemoryConflict
from lifereel_api.modules.production.locking import execution_lock

ACTIVE = {"queued", "running"}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def get_book(db, tenant, book_id):
    book = db.scalar(select(Book).where(Book.id == book_id, Book.tenant_id == tenant))
    if book is None:
        raise ApiError(404, ErrorCode.BOOK_NOT_FOUND)
    return book


def get_chapter(db, tenant, book_id, chapter_id):
    book = get_book(db, tenant, book_id)
    row = db.scalar(
        select(BookChapter).where(
            BookChapter.book_id == book.id,
            BookChapter.tenant_id == tenant,
            BookChapter.chapter_id == chapter_id,
        )
    )
    if row is None:
        raise ApiError(404, ErrorCode.BOOK_CHAPTER_NOT_FOUND)
    return book, row


def current_revision(db, row):
    return db.scalar(
        select(BookRevision).where(
            BookRevision.book_chapter_id == row.id,
            BookRevision.tenant_id == row.tenant_id,
            BookRevision.version_number == row.version_number,
        )
    )


def source(db, book, chapter_id):
    person = db.scalar(
        select(Person).where(
            Person.id == book.subject_id,
            Person.tenant_id == book.tenant_id,
        )
    )
    chapter = db.scalar(
        select(Chapter).where(
            Chapter.id == chapter_id,
            Chapter.tenant_id == book.tenant_id,
        )
    )
    if person is None or chapter is None:
        raise ApiError(404, ErrorCode.BOOK_CHAPTER_NOT_FOUND)
    excluded = set()
    for conflict in db.scalars(
        select(MemoryConflict).where(
            MemoryConflict.tenant_id == book.tenant_id,
            MemoryConflict.subject_id == book.subject_id,
            MemoryConflict.status == "open",
        )
    ):
        excluded.update(conflict.claim_ids)
    claims = list(
        db.scalars(
            select(MemoryClaim)
            .where(
                MemoryClaim.tenant_id == book.tenant_id,
                MemoryClaim.subject_id == book.subject_id,
                MemoryClaim.chapter_id == chapter_id,
                MemoryClaim.current_source(),
                MemoryClaim.review_status.not_in(["disputed", "private", "superseded"]),
            )
            .order_by(MemoryClaim.created_at, MemoryClaim.id)
        )
    )
    return {
        "subject_name": person.preferred_name or person.display_name,
        "chapter": chapter.title,
        "target_words": 1000,
        "claims": [
            {"id": str(c.id), "revision": c.source_revision, **fact_evidence(c)}
            for c in claims
            if str(c.id) not in excluded
        ],
    }


def create(db, tenant, payload):
    person = db.scalar(
        select(Person).where(
            Person.id == payload.subject_id,
            Person.tenant_id == tenant,
        )
    )
    if person is None:
        raise ApiError(404, ErrorCode.SUBJECT_NOT_FOUND)
    with execution_lock(db, person.id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.BOOK_GENERATION_BUSY)
        book = db.scalar(select(Book).where(Book.tenant_id == tenant, Book.subject_id == person.id))
        if book is None:
            book = Book(
                tenant_id=tenant,
                subject_id=person.id,
                title=payload.title or f"{person.preferred_name or person.display_name}的人生书",
            )
            db.add(book)
            db.flush()
        known = set(
            db.scalars(select(BookChapter.chapter_id).where(BookChapter.book_id == book.id))
        )
        for chapter in db.scalars(select(Chapter).where(Chapter.tenant_id == tenant)):
            if chapter.id not in known:
                db.add(BookChapter(tenant_id=tenant, book_id=book.id, chapter_id=chapter.id))
        db.commit()
        return read(db, tenant, book.id)


def read(db, tenant, book_id):
    book = get_book(db, tenant, book_id)
    rows = db.execute(
        select(BookChapter, Chapter)
        .join(
            Chapter,
            Chapter.id == BookChapter.chapter_id,
        )
        .where(BookChapter.book_id == book.id, BookChapter.tenant_id == tenant)
        .order_by(
            Chapter.order_index,
            Chapter.id,
        )
    ).all()
    result = []
    for row, chapter in rows:
        revision = current_revision(db, row)
        snapshot = source(db, book, chapter.id)
        job = db.get(Job, row.latest_job_id) if row.latest_job_id else None
        state = job.status if job else ("completed" if revision else "empty")
        if state == "failed" and job.error_code == ErrorCode.BOOK_MATERIAL_INSUFFICIENT.value:
            state = "needs_material"
        result.append(
            ChapterRead(
                id=row.id,
                chapter_id=chapter.id,
                title=chapter.title,
                order_index=chapter.order_index,
                version_number=row.version_number,
                status=state,
                source_count=len(snapshot["claims"]),
                stale=bool(revision and revision.source_digest != digest(snapshot)),
                job_id=row.latest_job_id,
                error_code=job.error_code if job else None,
                current=RevisionRead.model_validate(revision) if revision else None,
            )
        )
    return BookRead(
        id=book.id,
        subject_id=book.subject_id,
        title=book.title,
        target_words=book.target_words,
        chapters=result,
    )


def queue(db, tenant, book_id, payload):
    book = get_book(db, tenant, book_id)
    with execution_lock(db, book.id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.BOOK_GENERATION_BUSY)
        fingerprint = digest({"book_id": str(book.id), **payload.model_dump(mode="json")})
        prefix = f"book:{payload.idempotency_key}:"
        previous = list(
            db.scalars(
                select(Job).where(
                    Job.tenant_id == tenant,
                    Job.idempotency_key.startswith(prefix),
                )
            )
        )
        if previous:
            if any(j.payload.get("request_digest") != fingerprint for j in previous):
                raise ApiError(409, ErrorCode.BOOK_REQUEST_CONFLICT)
            return {
                "job_ids": [j.id for j in previous],
                "skipped_chapter_ids": previous[0].payload.get("skipped", []),
            }
        entries = list(
            db.scalars(
                select(BookChapter)
                .join(
                    Chapter,
                    Chapter.id == BookChapter.chapter_id,
                )
                .where(BookChapter.book_id == book.id, BookChapter.tenant_id == tenant)
                .order_by(
                    Chapter.order_index,
                    Chapter.id,
                )
            )
        )
        selected = set(payload.chapter_ids or [r.chapter_id for r in entries])
        if not selected <= {r.chapter_id for r in entries}:
            raise ApiError(404, ErrorCode.BOOK_CHAPTER_NOT_FOUND)
        work, skipped = [], []
        for row in entries:
            if row.chapter_id not in selected:
                continue
            snapshot = source(db, book, row.chapter_id)
            current = current_revision(db, row)
            job = db.get(Job, row.latest_job_id) if row.latest_job_id else None
            if job and job.status in ACTIVE:
                raise ApiError(409, ErrorCode.BOOK_GENERATION_BUSY)
            expected = payload.expected_versions.get(str(row.chapter_id), row.version_number)
            if expected != row.version_number:
                raise ApiError(409, ErrorCode.BOOK_VERSION_CONFLICT)
            if not snapshot["claims"] or (
                current and not payload.overwrite and current.source_digest == digest(snapshot)
            ):
                skipped.append(row.chapter_id)
                continue
            work.append((row, snapshot))
        if not work and not any(
            current_revision(db, row) for row in entries if row.chapter_id in selected
        ):
            raise ApiError(409, ErrorCode.BOOK_MATERIAL_INSUFFICIENT)
        identities = []
        for row, snapshot in work:
            job, _ = jobs.create_job(
                db,
                tenant,
                "book.chapter.generate",
                {
                    "book_id": str(book.id),
                    "book_chapter_id": str(row.id),
                    "chapter_id": str(row.chapter_id),
                    "expected_version": row.version_number,
                    "snapshot": snapshot,
                    "source_digest": digest(snapshot),
                    "request_digest": fingerprint,
                    "skipped": [str(i) for i in skipped],
                },
                prefix + str(row.chapter_id),
            )
            row.latest_job_id = job.id
            identities.append(job.id)
        db.commit()
        return {"job_ids": identities, "skipped_chapter_ids": skipped}


def transition(db, tenant, key, success):
    if distributed():
        enqueue_transition(db, tenant, key, success)
    else:
        billing.transition(db, tenant, key, success)


@track_usage("book")
def execute(db, tenant, job_id):
    job = jobs.get_job(db, tenant, job_id)
    if job.status == "completed":
        return
    row = db.scalar(
        select(BookChapter).where(
            BookChapter.id == UUID(job.payload["book_chapter_id"]),
            BookChapter.tenant_id == tenant,
        )
    )
    if row is None:
        raise ApiError(404, ErrorCode.BOOK_CHAPTER_NOT_FOUND)
    key = f"book-chapter:{job.id}"
    with execution_lock(db, row.id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.BOOK_GENERATION_BUSY)
        book = get_book(db, tenant, row.book_id)
        try:
            if row.latest_job_id != job.id or row.version_number != job.payload["expected_version"]:
                raise ApiError(409, ErrorCode.BOOK_VERSION_CONFLICT)
            if digest(source(db, book, row.chapter_id)) != job.payload["source_digest"]:
                raise ApiError(409, ErrorCode.BOOK_SOURCE_CHANGED)
            job.status = "running"
            db.commit()
            billing.reserve(
                db,
                tenant,
                key,
                billing.script_update_price(),
                "book",
                f"写书 · {book.title} · {job.payload['snapshot']['chapter']}",
                {**billing.prices(), "target_words": 1000},
            )
            db.commit()
            result = (job.result or {}).get("draft")
            if result is None:
                result = writing.generate(job.payload["snapshot"])
                job.result = {"draft": result}
                db.commit()
            db.expire_all()
            if digest(source(db, book, row.chapter_id)) != job.payload["source_digest"]:
                raise ApiError(409, ErrorCode.BOOK_SOURCE_CHANGED)
            if row.latest_job_id != job.id or row.version_number != job.payload["expected_version"]:
                raise ApiError(409, ErrorCode.BOOK_VERSION_CONFLICT)
            row.version_number += 1
            revision = BookRevision(
                tenant_id=tenant,
                book_chapter_id=row.id,
                version_number=row.version_number,
                **result,
                source_digest=job.payload["source_digest"],
                source_snapshot=job.payload["snapshot"],
                author="ai",
                generation_model=get_settings().model_for("script"),
            )
            db.add(revision)
            db.flush()
            job.status = "completed"
            job.error_code = job.error_message = None
            job.result = {"revision_id": str(revision.id), "version_number": row.version_number}
            transition(db, tenant, key, True)
            db.commit()
        except Exception:
            db.rollback()
            transition(db, tenant, key, False)
            db.commit()
            raise


def edit(db, tenant, book_id, chapter_id, payload):
    book, row = get_chapter(db, tenant, book_id, chapter_id)
    with execution_lock(db, row.id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.BOOK_GENERATION_BUSY)
        db.refresh(row)
        job = db.get(Job, row.latest_job_id) if row.latest_job_id else None
        if job and job.status in ACTIVE:
            raise ApiError(409, ErrorCode.BOOK_GENERATION_BUSY)
        previous = current_revision(db, row)
        if previous is None or payload.expected_version != row.version_number:
            raise ApiError(409, ErrorCode.BOOK_VERSION_CONFLICT)
        if payload.title == previous.title and payload.body == previous.body:
            return read(db, tenant, book.id)
        row.version_number += 1
        db.add(
            BookRevision(
                tenant_id=tenant,
                book_chapter_id=row.id,
                version_number=row.version_number,
                title=payload.title,
                body=payload.body,
                word_count=writing.word_count(payload.body),
                source_digest=previous.source_digest,
                source_snapshot=previous.source_snapshot,
                source_claim_ids=previous.source_claim_ids,
                author="user",
                generation_model=None,
            )
        )
        # Keep source freshness: a manual edit is not proof all corrected facts were applied.
        row.latest_job_id = None
        db.commit()
        return read(db, tenant, book.id)


def history(db, tenant, book_id, chapter_id):
    _, row = get_chapter(db, tenant, book_id, chapter_id)
    return list(
        db.scalars(
            select(BookRevision)
            .where(
                BookRevision.book_chapter_id == row.id,
                BookRevision.tenant_id == tenant,
            )
            .order_by(BookRevision.version_number.desc())
        )
    )


def retry(db, job):
    book, row = get_chapter(
        db, job.tenant_id, UUID(job.payload["book_id"]), UUID(job.payload["chapter_id"])
    )
    if job.status != "failed" or row.latest_job_id != job.id:
        raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
    if job.error_code in {
        ErrorCode.BOOK_SOURCE_CHANGED.value,
        ErrorCode.BOOK_OUTPUT_INVALID.value,
        ErrorCode.BOOK_MATERIAL_INSUFFICIENT.value,
        ErrorCode.MODEL_INVOCATION_UNCERTAIN.value,
    }:
        raise ApiError(409, ErrorCode.JOB_RETRY_NOT_ALLOWED)
    if digest(source(db, book, row.chapter_id)) != job.payload["source_digest"]:
        raise ApiError(409, ErrorCode.BOOK_SOURCE_CHANGED)
    job.status, job.error_code, job.error_message = "queued", None, None
    db.commit()
    return job

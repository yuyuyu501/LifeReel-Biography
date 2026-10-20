from uuid import UUID

from sqlalchemy import select

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.book import service
from lifereel_api.modules.book.models import Book, BookChapter, BookRevision


def sources(db, tenant, data):
    book = None
    if data.get("book_id"):
        book = service.get_book(db, tenant, UUID(data["book_id"]))
        if book.subject_id != UUID(data["subject_id"]):
            raise ApiError(404, ErrorCode.BOOK_NOT_FOUND)
        chapters = db.scalars(
            select(BookChapter).where(
                BookChapter.tenant_id == tenant,
                BookChapter.book_id == book.id,
                BookChapter.archived.is_(False),
            ).order_by(BookChapter.order_index, BookChapter.id)
        )
        ids = []
        for chapter in chapters:
            revision = service.current_revision(db, chapter)
            if revision:
                ids.append(revision.id)
        if not ids:
            raise ApiError(409, ErrorCode.BOOK_EMPTY)
    else:
        ids = list(map(UUID, data["revision_ids"]))
    if not ids or len(ids) > 40 or len(set(ids)) != len(ids):
        raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)
    result = []
    for revision_id in ids:
        found = db.execute(
            select(BookRevision, BookChapter, Book)
            .join(
                BookChapter,
                BookRevision.book_chapter_id == BookChapter.id,
            )
            .join(Book, BookChapter.book_id == Book.id)
            .where(
                BookRevision.id == revision_id,
                BookRevision.tenant_id == tenant,
                BookChapter.tenant_id == tenant,
                Book.tenant_id == tenant,
                Book.subject_id == UUID(data["subject_id"]),
                BookChapter.archived.is_(False),
            )
        ).first()
        if not found:
            raise ApiError(404, ErrorCode.BOOK_CHAPTER_NOT_FOUND)
        revision, chapter, source_book = found
        service.require_profile_sources(db, source_book)
        service.require_revision_sources(db, source_book, revision)
        snapshot = service.source(db, source_book, chapter.chapter_id or chapter.id)
        if snapshot.get("restricted_entry_ids"):
            raise ApiError(409, ErrorCode.PROFILE_USE_RESTRICTED)
        if (
            revision.version_number != chapter.version_number
            or service.digest(snapshot) != revision.source_digest
        ):
            raise ApiError(409, ErrorCode.BOOK_SOURCE_CHANGED)
        result.append(
            {
                "revision_id": str(revision.id),
                "book_id": str(source_book.id),
                "book_chapter_id": str(chapter.id),
                "version_number": revision.version_number,
                "title": revision.title,
                "body": revision.body,
                "source_digest": revision.source_digest,
                "source_entry_ids": revision.source_claim_ids,
                "preferences": snapshot.get("preferences", []),
            }
        )
    if sum(len(r["body"]) for r in result) > 65000:
        raise ApiError(413, ErrorCode.BOOK_INPUT_TOO_LARGE)
    output = {"subject_id": data["subject_id"], "revisions": result}
    if book:
        output.update(
            book_id=str(book.id), title=book.title, directory_version=book.directory_version,
        )
    return output

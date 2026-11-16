"""Import exported manuscripts as user-authored revisions, without model calls."""

import re
from pathlib import PurePath
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.book import profile_sources, service, writing
from lifereel_api.modules.book.models import Book, BookChapter, BookRevision
from lifereel_api.modules.identity.models import Person
from lifereel_api.modules.production.locking import execution_lock

MAX_BYTES = 2 * 1024 * 1024
EXTENSIONS = {".txt", ".md", ".markdown"}


def invalid():
    return ApiError(422, ErrorCode.BOOK_IMPORT_FORMAT_INVALID)


def parse(content: bytes, filename: str):
    extension = PurePath(filename).suffix.lower()
    if extension not in EXTENSIONS:
        raise invalid()
    if len(content) > MAX_BYTES:
        raise ApiError(413, ErrorCode.BOOK_IMPORT_TOO_LARGE)
    try:
        text = content.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        raise ApiError(422, ErrorCode.BOOK_IMPORT_ENCODING_INVALID) from None
    if not text.strip():
        raise ApiError(422, ErrorCode.BOOK_IMPORT_EMPTY)
    if any(ord(char) < 32 and char not in "\n\t" or 127 <= ord(char) < 160 for char in text):
        raise invalid()
    lines = text.strip("\n").split("\n")
    markdown = extension != ".txt"
    title = lines[0].removeprefix("# ") if markdown else lines[0]
    if markdown and not lines[0].startswith("# "):
        raise invalid()
    if not 1 <= len(title.strip()) <= 180:
        raise invalid()
    cursor = 1
    while cursor < len(lines) and not lines[cursor].strip():
        cursor += 1
    if cursor >= len(lines) or lines[cursor] != "目录":
        raise invalid()
    cursor += 1
    chapters = []
    while cursor < len(lines) and lines[cursor].strip():
        match = re.fullmatch(r"([1-9]\d*)\. (.+)", lines[cursor])
        if not match or int(match[1]) != len(chapters) + 1:
            raise invalid()
        heading = match[2]
        empty = heading.endswith("（未成稿）")
        for suffix in ("（未成稿）", "（资料已更新，待重写）"):
            if heading.endswith(suffix):
                heading = heading[:-len(suffix)]
                break
        if not 1 <= len(heading.strip()) <= 180 or len(chapters) >= 40:
            raise invalid()
        chapters.append({"title": heading, "body": None, "revision_title": heading})
        chapters[-1]["empty"] = empty
        cursor += 1
    while cursor < len(lines) and not lines[cursor].strip():
        cursor += 1
    populated = [chapter for chapter in chapters if not chapter["empty"]]
    if not populated or cursor >= len(lines):
        raise invalid()
    prose = lines[cursor:]
    if markdown:
        starts = [index for index, line in enumerate(prose) if line.startswith("## ")]
        if len(starts) != len(populated) or starts[0] != 0:
            raise invalid()
    else:
        starts = [0]
        for chapter in populated[1:]:
            candidates = [
                index for index in range(starts[-1] + 2, len(prose) - 1)
                if prose[index] == chapter["title"]
                and not prose[index - 1].strip() and not prose[index + 1].strip()
            ]
            if len(candidates) != 1:
                raise invalid()
            starts.append(candidates[0])
    for chapter, start, end in zip(populated, starts, [*starts[1:], len(prose)], strict=True):
        heading = prose[start][3:] if markdown else prose[start]
        if not 1 <= len(heading.strip()) <= 180:
            raise invalid()
        if start + 1 >= end or prose[start + 1].strip():
            raise invalid()
        body = "\n".join(prose[start + 2:end]).strip("\n")
        if not body.strip():
            raise invalid()
        chapter.update(revision_title=heading, body=body)
    return title.strip(), chapters


def import_book(db, tenant, subject_id, title, content, filename):
    person = db.scalar(select(Person).where(Person.id == subject_id, Person.tenant_id == tenant))
    if person is None:
        raise ApiError(404, ErrorCode.SUBJECT_NOT_FOUND)
    parsed_title, chapters = parse(content, filename)
    with execution_lock(db, person.id) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.BOOK_GENERATION_BUSY)
        if db.scalar(select(Book.id).where(
            Book.tenant_id == tenant, Book.subject_id == person.id,
        )):
            raise ApiError(409, ErrorCode.BOOK_ALREADY_EXISTS)
        # Fetch the profile before acquiring FK locks, matching normal book creation.
        profile = profile_sources.profile_read(db, tenant, subject_id=person.id)
        try:
            book = Book(
                tenant_id=tenant, subject_id=person.id, title=title or parsed_title,
                profile_id=UUID(profile["id"]), directory_version=2,
            )
            db.add(book)
            db.flush()
            for index, item in enumerate(chapters, 1):
                row = BookChapter(
                    tenant_id=tenant, book_id=book.id, title=item["title"],
                    order_index=index, source_entry_ids=[], version_number=0,
                )
                db.add(row)
                db.flush()
                if item["body"] is None:
                    continue
                snapshot = profile_sources.source(db, book, row.id, profile=profile)
                row.version_number = 1
                db.add(BookRevision(
                    tenant_id=tenant, book_chapter_id=row.id, version_number=1,
                    title=item["revision_title"], body=item["body"],
                    word_count=writing.word_count(item["body"]),
                    source_digest=service.digest(snapshot), source_snapshot=snapshot,
                    source_claim_ids=[], author="user", generation_model=None,
                ))
            db.flush()
            result = service.read(db, tenant, book.id)
            db.commit()
            return result
        except IntegrityError:
            db.rollback()
            if db.scalar(select(Book.id).where(
                Book.tenant_id == tenant, Book.subject_id == person.id,
            )):
                raise ApiError(409, ErrorCode.BOOK_ALREADY_EXISTS) from None
            raise
        except Exception:
            db.rollback()
            raise

"""Import exported manuscripts as user-authored revisions, without model calls."""

import re
from contextlib import nullcontext
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


def txt_sections(prose, chapters):
    isolated = [
        index for index, line in enumerate(prose)
        if line.strip() and (index == 0 or not prose[index - 1].strip())
        and index + 1 < len(prose) and not prose[index + 1].strip()
    ]
    marker = re.compile(r"【第([1-9]\d*)章】(.+)")
    if marker.fullmatch(prose[0]):
        marked = [
            (index, match) for index in isolated
            if (match := marker.fullmatch(prose[index]))
        ]
        if [int(match[1]) for _, match in marked] != [ch["order"] for ch in chapters]:
            raise invalid()
        return [index for index, _ in marked], [match[2] for _, match in marked]

    starts = [0]
    for chapter in chapters[1:]:
        candidates = [index for index in isolated if prose[index] == chapter["title"]]
        if len(candidates) > 1:
            raise invalid()
        if not candidates or candidates[0] <= starts[-1]:
            break
        starts.append(candidates[0])
    if len(starts) == len(chapters):
        return starts, [prose[index] for index in starts]

    # Older TXT exports have no chapter markers and can use different prose titles.
    # Accept only a complete, unambiguous set of standalone heading-like paragraphs.
    titles = {chapter["title"] for chapter in chapters}
    starts = [
        index for index in isolated
        if 1 <= len(prose[index].strip()) <= 180
        and (prose[index] in titles or not re.search(r"[。！？；.!?;]", prose[index]))
    ]
    if len(starts) != len(chapters) or starts[0] != 0:
        raise invalid()
    headings = [prose[index] for index in starts]
    if any(
        heading in titles and heading != chapter["title"]
        for heading, chapter in zip(headings, chapters, strict=True)
    ):
        raise invalid()
    return starts, headings


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
        chapters.append({
            "title": heading, "body": None, "revision_title": heading,
            "order": len(chapters) + 1,
        })
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
        headings = [prose[index][3:] for index in starts]
    else:
        starts, headings = txt_sections(prose, populated)
    for chapter, start, end, heading in zip(
        populated, starts, [*starts[1:], len(prose)], headings, strict=True,
    ):
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
    person = (
        db.scalar(select(Person).where(Person.id == subject_id, Person.tenant_id == tenant))
        if subject_id is not None else None
    )
    if subject_id is not None and person is None:
        raise ApiError(404, ErrorCode.SUBJECT_NOT_FOUND)
    parsed_title, chapters = parse(content, filename)
    with execution_lock(db, person.id) if person else nullcontext(True) as acquired:
        if not acquired:
            raise ApiError(409, ErrorCode.BOOK_GENERATION_BUSY)
        if person and db.scalar(select(Book.id).where(
            Book.tenant_id == tenant, Book.subject_id == person.id,
        )):
            raise ApiError(409, ErrorCode.BOOK_ALREADY_EXISTS)
        # Fetch the profile before acquiring FK locks, matching normal book creation.
        profile = profile_sources.profile_read(db, tenant, subject_id=person.id) if person else None
        try:
            book = Book(
                tenant_id=tenant, subject_id=person.id if person else None,
                title=title or parsed_title,
                profile_id=UUID(profile["id"]) if profile else None, directory_version=2,
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
                snapshot = (
                    profile_sources.source(db, book, row.id, profile=profile)
                    if profile else service.source(db, book, row.id)
                )
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
            if person and db.scalar(select(Book.id).where(
                Book.tenant_id == tenant, Book.subject_id == person.id,
            )):
                raise ApiError(409, ErrorCode.BOOK_ALREADY_EXISTS) from None
            raise
        except Exception:
            db.rollback()
            raise

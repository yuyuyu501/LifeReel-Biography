from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.database import get_db
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.book import service
from lifereel_api.modules.book.models import Book
from lifereel_api.modules.book.schemas import (
    BookCreate,
    BookGenerate,
    BookRead,
    ChapterEdit,
    DirectoryEdit,
    GenerationRead,
    RevisionRead,
)

router = APIRouter(prefix="/books", tags=["books"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[UUID, Depends(get_tenant_id)]


@router.get("", response_model=list[BookRead])
def list_books(db: Db, tenant: Tenant):
    return [
        service.read(db, tenant, row.id)
        for row in db.scalars(
            select(Book).where(Book.tenant_id == tenant).order_by(Book.created_at.desc())
        )
    ]


@router.post("", response_model=BookRead, status_code=201)
def create(payload: BookCreate, db: Db, tenant: Tenant):
    return service.create(db, tenant, payload)


@router.get("/{book_id}", response_model=BookRead)
def read(book_id: UUID, db: Db, tenant: Tenant):
    return service.read(db, tenant, book_id)


@router.patch("/{book_id}/directory", response_model=BookRead)
def directory(book_id: UUID, payload: DirectoryEdit, db: Db, tenant: Tenant):
    from lifereel_api.modules.book.profile_sources import edit_directory

    return edit_directory(db, tenant, book_id, payload)


@router.post("/{book_id}/generate", response_model=GenerationRead, status_code=202)
def generate(book_id: UUID, payload: BookGenerate, db: Db, tenant: Tenant):
    return service.queue(db, tenant, book_id, payload)


@router.patch("/{book_id}/chapters/{chapter_id}", response_model=BookRead)
def edit(book_id: UUID, chapter_id: UUID, payload: ChapterEdit, db: Db, tenant: Tenant):
    return service.edit(db, tenant, book_id, chapter_id, payload)


@router.get("/{book_id}/chapters/{chapter_id}/versions", response_model=list[RevisionRead])
def history(book_id: UUID, chapter_id: UUID, db: Db, tenant: Tenant):
    return service.history(db, tenant, book_id, chapter_id)


@router.get("/{book_id}/export")
def export(book_id: UUID, db: Db, tenant: Tenant, format: Literal["txt", "md"] = "txt"):
    model = service.get_book(db, tenant, book_id)
    service.require_profile_sources(db, model)
    book = service.read(db, tenant, book_id)
    if model.profile_id:
        from lifereel_api.modules.book.profile_sources import profile_read

        profile = profile_read(db, tenant, profile_id=model.profile_id)
        for chapter in book.chapters:
            if chapter.current:
                service.require_revision_sources(db, model, chapter.current, profile=profile)
                if service.source(db, model, chapter.chapter_id).get("restricted_entry_ids"):
                    raise ApiError(409, ErrorCode.PROFILE_USE_RESTRICTED)
    if not any(ch.current for ch in book.chapters):
        raise ApiError(409, ErrorCode.BOOK_EMPTY)
    lines = [("# " if format == "md" else "") + book.title, "", "目录"]
    for ch in book.chapters:
        suffix = "（未成稿）" if not ch.current else "（资料已更新，待重写）" if ch.stale else ""
        lines.append(f"{ch.order_index}. {ch.title}{suffix}")
    for ch in book.chapters:
        if ch.current:
            lines.extend(
                ["", ("## " if format == "md" else "") + ch.current.title, "", ch.current.body]
            )
    return Response(
        "\n".join(lines),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="book-{book.id}.{format}"',
            "Cache-Control": "private, no-store",
        },
    )

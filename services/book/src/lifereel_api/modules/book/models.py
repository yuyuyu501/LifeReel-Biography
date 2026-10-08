from uuid import UUID

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from lifereel_api.core.database import Base
from lifereel_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class Book(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "books"
    __table_args__ = (
        UniqueConstraint("tenant_id", "subject_id", name="uq_book_tenant_subject"),
        {"schema": "book"},
    )
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.persons.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(180))
    target_words: Mapped[int] = mapped_column(Integer, default=1000, server_default="1000")
    profile_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("interview.life_profiles.id", ondelete="SET NULL"), nullable=True
    )
    directory_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class BookChapter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "book_chapters"
    __table_args__ = (
        UniqueConstraint("book_id", "chapter_id", name="uq_book_chapter"),
        {"schema": "book"},
    )
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.tenants.id", ondelete="CASCADE"), index=True
    )
    book_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("book.books.id", ondelete="CASCADE"), index=True
    )
    chapter_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("interview.chapters.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(180), default="新章节", server_default="新章节")
    order_index: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    source_entry_ids: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    version_number: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    latest_job_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("tasks.jobs.id", ondelete="SET NULL"), nullable=True
    )


class BookRevision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "book_revisions"
    __table_args__ = (
        UniqueConstraint("book_chapter_id", "version_number", name="uq_book_revision_version"),
        {"schema": "book"},
    )
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.tenants.id", ondelete="CASCADE"), index=True
    )
    book_chapter_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("book.book_chapters.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer)
    source_digest: Mapped[str] = mapped_column(String(64))
    source_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    source_claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    author: Mapped[str] = mapped_column(String(24))
    generation_model: Mapped[str | None] = mapped_column(String(180), nullable=True)

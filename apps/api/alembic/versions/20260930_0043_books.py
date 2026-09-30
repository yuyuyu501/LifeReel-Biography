"""Add a separately owned book namespace and durable chapter revisions."""

import sqlalchemy as sa

from alembic import op

revision = "20260930_0043"
down_revision = "20260930_0042"
branch_labels = None
depends_on = None
TABLES = ("books", "book_chapters", "book_revisions")


def upgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    schema = "book" if pg else None
    if pg:
        op.execute("CREATE SCHEMA IF NOT EXISTS book")

    def reference(name):
        return name if pg else ".".join(name.split(".")[-2:])

    def common():
        return [
            sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "tenant_id",
                sa.Uuid(),
                sa.ForeignKey(reference("identity.tenants.id"), ondelete="CASCADE"),
                nullable=False,
            ),
        ]

    op.create_table(
        "books",
        *common(),
        sa.Column(
            "subject_id",
            sa.Uuid(),
            sa.ForeignKey(reference("identity.persons.id"), ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("target_words", sa.Integer(), nullable=False, server_default="1000"),
        sa.UniqueConstraint("tenant_id", "subject_id", name="uq_book_tenant_subject"),
        schema=schema,
    )
    op.create_table(
        "book_chapters",
        *common(),
        sa.Column(
            "book_id",
            sa.Uuid(),
            sa.ForeignKey(reference("book.books.id"), ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chapter_id",
            sa.Uuid(),
            sa.ForeignKey(reference("interview.chapters.id"), ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "latest_job_id",
            sa.Uuid(),
            sa.ForeignKey(reference("tasks.jobs.id"), ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("book_id", "chapter_id", name="uq_book_chapter"),
        schema=schema,
    )
    op.create_table(
        "book_revisions",
        *common(),
        sa.Column(
            "book_chapter_id",
            sa.Uuid(),
            sa.ForeignKey(reference("book.book_chapters.id"), ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("source_claim_ids", sa.JSON(), nullable=False),
        sa.Column("author", sa.String(24), nullable=False),
        sa.Column("generation_model", sa.String(180), nullable=True),
        sa.UniqueConstraint("book_chapter_id", "version_number", name="uq_book_revision_version"),
        schema=schema,
    )
    for table, columns in {
        "books": ("tenant_id", "subject_id"),
        "book_chapters": ("tenant_id", "book_id", "chapter_id"),
        "book_revisions": ("tenant_id", "book_chapter_id"),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column], schema=schema)


def downgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    schema, prefix = ("book", "book.") if pg else (None, "")
    if op.get_bind().scalar(sa.text(f"SELECT count(*) FROM {prefix}books")):
        raise RuntimeError("Book data exists; export/restore explicitly before downgrade")
    for table in reversed(TABLES):
        op.drop_table(table, schema=schema)
    if pg:
        op.execute("DROP SCHEMA book")

"""Persist source-grounded book fact-check reports."""

import sqlalchemy as sa

from alembic import op

revision = "20261105_0046"
down_revision = "20261012_0045"
branch_labels = None
depends_on = None


def upgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    schema = "book" if pg else None

    def ref(name):
        return name if pg else ".".join(name.split(".")[-2:])

    op.create_table(
        "book_fact_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(ref("identity.tenants.id"), ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "book_id",
            sa.Uuid(),
            sa.ForeignKey(ref("book.books.id"), ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey(ref("tasks.jobs.id"), ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "book_id", "request_id", name="uq_book_fact_check_request"
        ),
        schema=schema,
    )
    op.create_index(
        "ix_book_fact_checks_tenant_id",
        "book_fact_checks",
        ["tenant_id"],
        schema=schema,
    )
    op.create_index(
        "ix_book_fact_checks_book_id",
        "book_fact_checks",
        ["book_id"],
        schema=schema,
    )


def downgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    table = "book.book_fact_checks" if pg else "book_fact_checks"
    if op.get_bind().scalar(sa.text(f"SELECT count(*) FROM {table}")):
        raise RuntimeError(
            "Book fact-check reports exist; export/restore explicitly before downgrade"
        )
    op.drop_table("book_fact_checks", schema="book" if pg else None)

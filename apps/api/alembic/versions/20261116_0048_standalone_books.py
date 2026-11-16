"""Allow imported manuscripts without a person association."""

import sqlalchemy as sa

from alembic import op

revision = "20261116_0048"
down_revision = "20261106_0047"
branch_labels = None
depends_on = None


def set_nullable(nullable):
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("books", "subject_id", schema="book", nullable=nullable)
    else:
        with op.batch_alter_table("books") as batch:
            batch.alter_column("subject_id", existing_type=sa.Uuid(), nullable=nullable)


def upgrade():
    set_nullable(True)


def downgrade():
    table = "book.books" if op.get_bind().dialect.name == "postgresql" else "books"
    if op.get_bind().execute(
        sa.text(f"SELECT id FROM {table} WHERE subject_id IS NULL LIMIT 1")
    ).first():
        raise RuntimeError("Standalone books exist; associate or explicitly remove them first")
    set_nullable(False)

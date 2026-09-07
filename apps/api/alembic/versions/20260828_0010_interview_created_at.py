"""add missing interview session creation timestamp

Revision ID: 20260828_0010
Revises: 20260828_0009
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_0010"
down_revision: str | None = "20260828_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("interview_sessions") as batch_op:
        batch_op.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        sa.text("UPDATE interview_sessions SET created_at = started_at WHERE created_at IS NULL")
    )
    with op.batch_alter_table("interview_sessions") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("interview_sessions") as batch_op:
        batch_op.drop_column("created_at")

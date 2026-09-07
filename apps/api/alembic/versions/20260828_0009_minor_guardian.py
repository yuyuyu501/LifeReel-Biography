"""minor and guardian fields

Revision ID: 20260828_0009
Revises: 20260828_0008
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_0009"
down_revision: str | None = "20260828_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "persons", sa.Column("is_minor", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("persons", sa.Column("guardian_name", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("persons", "guardian_name")
    op.drop_column("persons", "is_minor")

"""store evidence sizes as big integers

Revision ID: 20260828_0011
Revises: 20260828_0010
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_0011"
down_revision: str | None = "20260828_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("source_assets") as batch_op:
        batch_op.alter_column(
            "byte_size",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("source_assets") as batch_op:
        batch_op.alter_column(
            "byte_size",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )

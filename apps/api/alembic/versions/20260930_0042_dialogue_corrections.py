"""Keep original sources while applying facts corrected in later conversation."""

import sqlalchemy as sa

from alembic import op

revision = "20260930_0042"
down_revision = "20260929_0041"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "memory_claims",
        sa.Column("fact_overrides", sa.JSON(), nullable=False, server_default="[]"),
        schema="memory" if op.get_bind().dialect.name == "postgresql" else None,
    )


def downgrade():
    op.drop_column(
        "memory_claims", "fact_overrides",
        schema="memory" if op.get_bind().dialect.name == "postgresql" else None,
    )

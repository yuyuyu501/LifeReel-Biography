"""Retain precise token charges independently of script success."""

import sqlalchemy as sa

from alembic import op

revision = "20260911_0022"
down_revision = "20260910_0021"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "wallets",
        sa.Column("token_remainder_nano", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "provider_usage", sa.Column("metering", sa.JSON(), nullable=False, server_default="{}")
    )


def downgrade():
    op.drop_column("provider_usage", "metering")
    op.drop_column("wallets", "token_remainder_nano")

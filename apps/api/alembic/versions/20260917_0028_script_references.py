"""Persist chapter image and audio reference selections.

Revision ID: 20260917_0028
Revises: 20260916_0027
"""

import sqlalchemy as sa

from alembic import op

revision = "20260917_0028"
down_revision = "20260916_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("script_scenes", sa.Column("reference_asset_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("script_scenes", "reference_asset_ids")

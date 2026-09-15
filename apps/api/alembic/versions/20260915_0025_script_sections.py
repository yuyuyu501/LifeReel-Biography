"""Persist plot and spoken lines separately from camera directions."""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0025"
down_revision = "20260914_0024"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("script_scenes", sa.Column("plot", sa.Text(), nullable=True))
    op.add_column("script_scenes", sa.Column("dialogues", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("script_scenes", "dialogues")
    op.drop_column("script_scenes", "plot")

"""Persist structured visual constraints for script scenes and shots.

Revision ID: 20260923_0032
Revises: 20260921_0031
"""

import sqlalchemy as sa

from alembic import op

revision = "20260923_0032"
down_revision = "20260921_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("script_scenes", sa.Column("visual_constraints", sa.JSON(), nullable=True))
    op.add_column("script_shots", sa.Column("visual_constraints", sa.JSON(), nullable=True))
    op.add_column("script_scenes", sa.Column("story_skeleton", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("script_shots", "visual_constraints")
    op.drop_column("script_scenes", "story_skeleton")
    op.drop_column("script_scenes", "visual_constraints")

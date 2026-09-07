"""script versions locking and shots

Revision ID: 20260828_0006
Revises: 20260828_0005
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_0006"
down_revision: str | None = "20260828_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "script_projects",
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "script_projects", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "script_shots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("scene_id", sa.Uuid(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("shot_type", sa.String(length=48), nullable=False),
        sa.Column("visual_prompt", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("source_claim_ids", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["scene_id"], ["script_scenes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_script_shots_tenant_id", "script_shots", ["tenant_id"])
    op.create_index("ix_script_shots_scene_id", "script_shots", ["scene_id"])


def downgrade() -> None:
    op.drop_table("script_shots")
    op.drop_column("script_projects", "locked_at")
    op.drop_column("script_projects", "version_number")

"""Persist structured book-to-screen planning artifacts."""

import sqlalchemy as sa

from alembic import op

revision = "20261106_0047"
down_revision = "20261105_0046"
branch_labels = None
depends_on = None


def upgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    for name in ("adaptation_brief", "story_bible", "sequence_plan"):
        op.add_column(
            "script_projects",
            sa.Column(name, sa.JSON(), nullable=True),
            schema="script" if pg else None,
        )
    for table in ("script_scenes", "script_shots"):
        op.add_column(
            table,
            sa.Column("adaptation_metadata", sa.JSON(), nullable=False, server_default="{}"),
            schema="script" if pg else None,
        )


def downgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    schema = "script" if pg else None
    for table in ("script_shots", "script_scenes"):
        op.drop_column(table, "adaptation_metadata", schema=schema)
    for name in ("sequence_plan", "story_bible", "adaptation_brief"):
        op.drop_column("script_projects", name, schema=schema)

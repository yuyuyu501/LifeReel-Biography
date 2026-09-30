"""Version interview corrections without replacing original recordings."""

import sqlalchemy as sa

from alembic import op

revision = "20260929_0041"
down_revision = "20260929_0040"
branch_labels = None
depends_on = None


def upgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    op.add_column(
        "interview_rounds",
        sa.Column("answer_version", sa.Integer(), nullable=False, server_default="1"),
        schema="interview" if pg else None,
    )
    op.add_column(
        "interview_rounds",
        sa.Column("answer_revisions", sa.JSON(), nullable=False, server_default="[]"),
        schema="interview" if pg else None,
    )
    op.add_column(
        "memory_claims",
        sa.Column("source_revision", sa.Integer(), nullable=False, server_default="1"),
        schema="memory" if pg else None,
    )


def downgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    op.drop_column("memory_claims", "source_revision", schema="memory" if pg else None)
    op.drop_column("interview_rounds", "answer_revisions", schema="interview" if pg else None)
    op.drop_column("interview_rounds", "answer_version", schema="interview" if pg else None)

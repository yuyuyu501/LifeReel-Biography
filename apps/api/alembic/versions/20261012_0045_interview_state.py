"""Persist person interview strategy and boundaries across turns."""

import sqlalchemy as sa

from alembic import op

revision = "20261012_0045"
down_revision = "20261008_0044"
branch_labels = None
depends_on = None


def upgrade():
    schema = "interview" if op.get_bind().dialect.name == "postgresql" else None
    op.add_column(
        "interview_sessions",
        sa.Column("interview_state", sa.JSON(), nullable=False, server_default="{}"),
        schema=schema,
    )
    op.add_column(
        "interview_rounds",
        sa.Column("question_sources", sa.JSON(), nullable=False, server_default="[]"),
        schema=schema,
    )


def downgrade():
    schema = "interview" if op.get_bind().dialect.name == "postgresql" else None
    count = op.get_bind().scalar(
        sa.text(
            f"SELECT count(*) FROM {'interview.' if schema else ''}interview_sessions "
            "WHERE CAST(interview_state AS TEXT) <> '{}'"
        )
    )
    citations = op.get_bind().scalar(
        sa.text(
            f"SELECT count(*) FROM {'interview.' if schema else ''}interview_rounds "
            "WHERE CAST(question_sources AS TEXT) <> '[]'"
        )
    )
    if count or citations:
        raise RuntimeError("Interview state exists; export it before downgrading")
    op.drop_column("interview_sessions", "interview_state", schema=schema)
    op.drop_column("interview_rounds", "question_sources", schema=schema)

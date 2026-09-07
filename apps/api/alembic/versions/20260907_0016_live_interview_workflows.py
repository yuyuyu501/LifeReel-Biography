"""Add persisted live interview turn workflows.

Revision ID: 20260907_0016
Revises: 20260907_0015
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_0016"
down_revision: str | None = "20260907_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_turn_workflows",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("chapter_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("asset_ids", sa.JSON(), nullable=False),
        sa.Column("source_claim_ids", sa.JSON(), nullable=False),
        sa.Column("script_scene_ids", sa.JSON(), nullable=False),
        sa.Column("script_project_id", sa.Uuid(), nullable=True),
        sa.Column("next_question", sa.Text(), nullable=True),
        sa.Column("next_question_intent", sa.String(length=80), nullable=True),
        sa.Column("missing_topics", sa.JSON(), nullable=False),
        sa.Column("script_brief", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["round_id"], ["interview_rounds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_interview_turn_tenant_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_interview_turn_workflows_tenant_id"),
        "interview_turn_workflows",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_interview_turn_workflows_session_id"),
        "interview_turn_workflows",
        ["session_id"],
    )
    op.create_index(
        op.f("ix_interview_turn_workflows_round_id"),
        "interview_turn_workflows",
        ["round_id"],
    )
    op.create_index(
        op.f("ix_interview_turn_workflows_chapter_id"),
        "interview_turn_workflows",
        ["chapter_id"],
    )
    op.create_index(
        op.f("ix_interview_turn_workflows_job_id"),
        "interview_turn_workflows",
        ["job_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_interview_turn_workflows_job_id"), table_name="interview_turn_workflows")
    op.drop_index(
        op.f("ix_interview_turn_workflows_chapter_id"),
        table_name="interview_turn_workflows",
    )
    op.drop_index(
        op.f("ix_interview_turn_workflows_round_id"),
        table_name="interview_turn_workflows",
    )
    op.drop_index(
        op.f("ix_interview_turn_workflows_session_id"),
        table_name="interview_turn_workflows",
    )
    op.drop_index(
        op.f("ix_interview_turn_workflows_tenant_id"),
        table_name="interview_turn_workflows",
    )
    op.drop_table("interview_turn_workflows")

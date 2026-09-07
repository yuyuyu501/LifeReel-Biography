"""evidence-backed memory claims and script drafts

Revision ID: 20260828_0002
Revises: 20260828_0001
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_0002"
down_revision: str | None = "20260828_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("interview_session_id", sa.Uuid(), nullable=False),
        sa.Column("source_round_id", sa.Uuid(), nullable=False),
        sa.Column("chapter_id", sa.Uuid(), nullable=True),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("source_quote", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(length=48), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["interview_session_id"], ["interview_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["source_round_id"], ["interview_rounds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "source_round_id", name="uq_claim_tenant_source_round"
        ),
    )
    op.create_index("ix_memory_claims_tenant_id", "memory_claims", ["tenant_id"])
    op.create_index("ix_memory_claims_subject_id", "memory_claims", ["subject_id"])
    op.create_index(
        "ix_memory_claims_interview_session_id",
        "memory_claims",
        ["interview_session_id"],
    )

    op.create_table(
        "script_projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("audience", sa.String(length=32), nullable=False),
        sa.Column("source_claim_ids", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["subject_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_script_projects_tenant_id", "script_projects", ["tenant_id"])
    op.create_index("ix_script_projects_subject_id", "script_projects", ["subject_id"])

    op.create_table(
        "script_scenes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(length=180), nullable=False),
        sa.Column("narration", sa.Text(), nullable=False),
        sa.Column("visual_prompt", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("source_claim_ids", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["script_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_script_scenes_tenant_id", "script_scenes", ["tenant_id"])
    op.create_index("ix_script_scenes_project_id", "script_scenes", ["project_id"])


def downgrade() -> None:
    op.drop_table("script_scenes")
    op.drop_table("script_projects")
    op.drop_table("memory_claims")

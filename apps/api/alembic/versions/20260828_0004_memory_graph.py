"""memory entities timeline and conflicts

Revision ID: 20260828_0004
Revises: 20260828_0003
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_0004"
down_revision: str | None = "20260828_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_entities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("normalized_name", sa.String(length=180), nullable=False),
        sa.Column("source_claim_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["subject_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "subject_id", "entity_type", "normalized_name", name="uq_memory_entity"
        ),
    )
    op.create_index("ix_memory_entities_tenant_id", "memory_entities", ["tenant_id"])
    op.create_index("ix_memory_entities_subject_id", "memory_entities", ["subject_id"])

    op.create_table(
        "timeline_anchors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("time_text", sa.String(length=120), nullable=False),
        sa.Column("event_text", sa.Text(), nullable=False),
        sa.Column("precision", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["memory_claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_timeline_anchors_tenant_id", "timeline_anchors", ["tenant_id"])
    op.create_index("ix_timeline_anchors_subject_id", "timeline_anchors", ["subject_id"])
    op.create_index("ix_timeline_anchors_claim_id", "timeline_anchors", ["claim_id"])

    op.create_table(
        "memory_conflicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("claim_ids", sa.JSON(), nullable=False),
        sa.Column("conflict_key", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["subject_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_conflicts_tenant_id", "memory_conflicts", ["tenant_id"])
    op.create_index("ix_memory_conflicts_subject_id", "memory_conflicts", ["subject_id"])


def downgrade() -> None:
    op.drop_table("memory_conflicts")
    op.drop_table("timeline_anchors")
    op.drop_table("memory_entities")

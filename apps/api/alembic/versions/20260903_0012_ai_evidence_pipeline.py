"""AI evidence observations and traceable material claims

Revision ID: 20260903_0012
Revises: 20260828_0011
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260903_0012"
down_revision: str | None = "20260828_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_id", sa.Uuid(), nullable=False),
        sa.Column("source_transcript_version_id", sa.Uuid(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("analysis_kind", sa.String(length=48), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_name", sa.String(length=180), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_asset_id"], ["source_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_transcript_version_id"], ["transcript_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["subject_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "source_asset_id",
            "version_number",
            name="uq_evidence_observation_version",
        ),
    )
    op.create_index("ix_evidence_observations_tenant_id", "evidence_observations", ["tenant_id"])
    op.create_index("ix_evidence_observations_subject_id", "evidence_observations", ["subject_id"])
    op.create_index(
        "ix_evidence_observations_source_asset_id", "evidence_observations", ["source_asset_id"]
    )

    op.alter_column("memory_claims", "interview_session_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("memory_claims", "source_round_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("memory_claims", sa.Column("source_observation_id", sa.Uuid(), nullable=True))
    op.add_column(
        "memory_claims",
        sa.Column("extraction_provider", sa.String(length=80), nullable=False, server_default="rule"),
    )
    op.add_column(
        "memory_claims", sa.Column("extraction_model", sa.String(length=180), nullable=True)
    )
    op.create_foreign_key(
        "fk_memory_claims_source_observation_id_evidence_observations",
        "memory_claims",
        "evidence_observations",
        ["source_observation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_claim_tenant_source_observation",
        "memory_claims",
        ["tenant_id", "source_observation_id"],
    )
    op.add_column(
        "script_projects",
        sa.Column("generation_provider", sa.String(length=80), nullable=False, server_default="rule"),
    )
    op.add_column(
        "script_projects", sa.Column("generation_model", sa.String(length=180), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("script_projects", "generation_model")
    op.drop_column("script_projects", "generation_provider")
    op.drop_constraint(
        "uq_claim_tenant_source_observation", "memory_claims", type_="unique"
    )
    op.drop_constraint(
        "fk_memory_claims_source_observation_id_evidence_observations",
        "memory_claims",
        type_="foreignkey",
    )
    op.drop_column("memory_claims", "source_observation_id")
    op.drop_column("memory_claims", "extraction_model")
    op.drop_column("memory_claims", "extraction_provider")
    op.alter_column("memory_claims", "source_round_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("memory_claims", "interview_session_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_table("evidence_observations")

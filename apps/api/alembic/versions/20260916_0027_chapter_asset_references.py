"""Add chapter age metadata and consent-aware asset reference metadata."""

import sqlalchemy as sa

from alembic import op

revision = "20260916_0027"
down_revision = "20260915_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("chapters") as batch:
        batch.add_column(sa.Column("age_start", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("age_end", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("age_confidence", sa.Float(), nullable=True))
        batch.add_column(sa.Column("age_source", sa.String(32), nullable=True))
    with op.batch_alter_table("source_assets") as batch:
        batch.add_column(sa.Column("chapter_id", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column("consent_status", sa.String(24), server_default="unknown", nullable=False)
        )
        batch.add_column(sa.Column("age_start", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("age_end", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("quality_score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("identity_score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("voice_score", sa.Float(), nullable=True))
        batch.add_column(
            sa.Column("analysis_status", sa.String(24), server_default="pending", nullable=False)
        )
        batch.add_column(sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("derived_from_asset_id", sa.Uuid(), nullable=True))
        batch.create_index("ix_source_assets_chapter_id", ["chapter_id"])
    op.execute("UPDATE source_assets SET consent_status='granted' WHERE consent_status='unknown'")
    with op.batch_alter_table("evidence_uploads") as batch:
        batch.add_column(sa.Column("chapter_id", sa.Uuid(), nullable=True))
        batch.create_index("ix_evidence_uploads_chapter_id", ["chapter_id"])
    op.create_table(
        "chapter_reference_packages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "production_run_id",
            sa.Uuid(),
            sa.ForeignKey("production_runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "subject_id", sa.Uuid(), sa.ForeignKey("persons.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("chapter_id", sa.Uuid(), sa.ForeignKey("chapters.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(24), nullable=False, server_default="ready"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_chapter_reference_packages_tenant_id", "chapter_reference_packages", ["tenant_id"]
    )
    op.create_index(
        "ix_chapter_reference_packages_subject_id", "chapter_reference_packages", ["subject_id"]
    )


def downgrade() -> None:
    op.drop_table("chapter_reference_packages")
    with op.batch_alter_table("evidence_uploads") as batch:
        batch.drop_index("ix_evidence_uploads_chapter_id")
        batch.drop_column("chapter_id")
    with op.batch_alter_table("source_assets") as batch:
        batch.drop_index("ix_source_assets_chapter_id")
        for name in (
            "derived_from_asset_id",
            "metadata",
            "analysis_status",
            "voice_score",
            "identity_score",
            "quality_score",
            "age_end",
            "age_start",
            "consent_status",
            "chapter_id",
        ):
            batch.drop_column(name)
    with op.batch_alter_table("chapters") as batch:
        for name in ("age_source", "age_confidence", "age_end", "age_start"):
            batch.drop_column(name)

"""Track scoped OSS uploads separately from verified source assets."""

import sqlalchemy as sa

from alembic import op

revision = "20260910_0021"
down_revision = "20260909_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evidence_uploads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "subject_id", sa.Uuid(), sa.ForeignKey("persons.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "interview_session_id",
            sa.Uuid(),
            sa.ForeignKey("interview_sessions.id", ondelete="SET NULL"),
        ),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("consent_scope", sa.String(32), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("source_assets.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evidence_uploads_tenant_id", "evidence_uploads", ["tenant_id"])


def downgrade():
    op.drop_table("evidence_uploads")

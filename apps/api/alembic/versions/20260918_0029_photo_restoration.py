"""Account-scoped originals for standalone photo restoration.

Revision ID: 20260918_0029
Revises: 20260917_0028
"""

import sqlalchemy as sa

from alembic import op

revision = "20260918_0029"
down_revision = "20260917_0028"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "restoration_photos",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "sha256", name="uq_restore_photo_hash"),
    )
    op.create_index("ix_restoration_photos_tenant_id", "restoration_photos", ["tenant_id"])


def downgrade():
    op.drop_index("ix_restoration_photos_tenant_id", table_name="restoration_photos")
    op.drop_table("restoration_photos")

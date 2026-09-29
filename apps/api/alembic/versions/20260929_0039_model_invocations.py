"""Fence paid model retries across process/network failures."""

import sqlalchemy as sa

from alembic import op

revision = "20260929_0039"
down_revision = "20260929_0038"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_invocations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("operation", sa.String(120), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("model_invocations")

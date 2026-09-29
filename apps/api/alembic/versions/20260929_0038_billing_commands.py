"""Billing deduplication and script result receipts."""

import sqlalchemy as sa

from alembic import op

revision = "20260929_0038"
down_revision = "20260929_0037"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "billing_commands",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("result", sa.JSON(), nullable=False),
    )
    op.create_table(
        "script_generation_receipts",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("script_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )


def downgrade():
    op.drop_table("script_generation_receipts")
    op.drop_table("billing_commands")

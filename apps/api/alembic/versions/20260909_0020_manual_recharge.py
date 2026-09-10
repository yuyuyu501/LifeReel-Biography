"""Manual WeChat test orders; only server operators can credit a payment."""

import sqlalchemy as sa

from alembic import op

revision = "20260909_0020"
down_revision = "20260909_0019"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recharge_orders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("wallets.tenant_id"), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payer_reference", sa.String(64)),
        sa.Column("verified_reference", sa.String(64)),
        sa.Column("reviewed_by", sa.String(100)),
        sa.Column("review_note", sa.String(300)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "request_id"),
        sa.UniqueConstraint("verified_reference"),
        sa.CheckConstraint("amount_cents BETWEEN 1 AND 20000", name="recharge_amount"),
        sa.CheckConstraint(
            "status IN ('pending', 'submitted', 'credited', 'rejected', 'cancelled')",
            name="recharge_status",
        ),
    )
    op.create_index("ix_recharge_orders_tenant_id", "recharge_orders", ["tenant_id"])


def downgrade():
    op.drop_table("recharge_orders")

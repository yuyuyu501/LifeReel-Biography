"""Persist payment settlement origin; preserve every existing manual order."""

import sqlalchemy as sa

from alembic import op

revision = "20261118_0049"
down_revision = "20261116_0048"
branch_labels = None
depends_on = None


def upgrade():
    schema = "billing" if op.get_bind().dialect.name == "postgresql" else None
    op.add_column(
        "recharge_orders",
        sa.Column("settlement", sa.String(24), nullable=False, server_default="manual_review"),
        schema=schema,
    )
    op.add_column("recharge_orders", sa.Column("alipay_app_id", sa.String(32)), schema=schema)
    op.add_column(
        "recharge_orders",
        sa.Column("payment_checked_at", sa.DateTime(timezone=True)),
        schema=schema,
    )


def downgrade():
    schema = "billing" if op.get_bind().dialect.name == "postgresql" else None
    table = "billing.recharge_orders" if schema else "recharge_orders"
    if (
        op.get_bind()
        .execute(sa.text(f"SELECT id FROM {table} WHERE settlement <> 'manual_review' LIMIT 1"))
        .first()
    ):
        raise RuntimeError("API payment orders exist; preserve settlement provenance")
    op.drop_column("recharge_orders", "payment_checked_at", schema=schema)
    op.drop_column("recharge_orders", "alipay_app_id", schema=schema)
    op.drop_column("recharge_orders", "settlement", schema=schema)

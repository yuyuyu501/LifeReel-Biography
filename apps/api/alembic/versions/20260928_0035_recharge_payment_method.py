"""Record payment channels without relabelling historical WeChat receipts."""

import sqlalchemy as sa

from alembic import op

revision = "20260928_0035"
down_revision = "20260924_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recharge_orders",
        sa.Column("payment_method", sa.String(16), nullable=False, server_default="wechat"),
    )
    op.create_check_constraint(
        "recharge_payment_method",
        "recharge_orders",
        "payment_method IN ('wechat', 'alipay')",
    )


def downgrade() -> None:
    # Dropping this column after collecting Alipay payments loses receipt provenance.
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM recharge_orders WHERE payment_method = 'alipay'")
    ):
        raise RuntimeError("Cannot remove payment channels while Alipay orders exist")
    op.drop_constraint("recharge_payment_method", "recharge_orders", type_="check")
    op.drop_column("recharge_orders", "payment_method")

"""Wallet balances, immutable ledger, charges and provider usage."""

import sqlalchemy as sa

from alembic import op

revision = "20260909_0019"
down_revision = "20260907_0018"
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.create_table(
        "wallets",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), primary_key=True),
        *[
            sa.Column(name, sa.Integer(), nullable=False)
            for name in ["paid_cents", "bonus_cents", "frozen_paid_cents", "frozen_bonus_cents"]
        ],
        *timestamps(),
        sa.CheckConstraint("paid_cents >= 0 AND bonus_cents >= 0", name="nonnegative_balance"),
        sa.CheckConstraint(
            "frozen_paid_cents >= 0 AND frozen_bonus_cents >= 0", name="nonnegative_frozen"
        ),
        sa.CheckConstraint(
            "paid_cents >= frozen_paid_cents AND bonus_cents >= frozen_bonus_cents",
            name="covered_frozen",
        ),
    )
    op.create_table(
        "billing_charges",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("wallets.tenant_id"), nullable=False),
        sa.Column("business_key", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        *[
            sa.Column(name, sa.Integer(), nullable=False)
            for name in ["amount_cents", "paid_cents", "bonus_cents", "attempt"]
        ],
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("price_snapshot", sa.JSON(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("tenant_id", "business_key"),
        sa.CheckConstraint(
            "amount_cents >= 0 AND paid_cents >= 0 AND bonus_cents >= 0", name="positive_charge"
        ),
        sa.CheckConstraint("amount_cents = paid_cents + bonus_cents", name="charge_split"),
        sa.CheckConstraint("status IN ('reserved', 'settled', 'released')", name="valid_status"),
    )
    op.create_index("ix_billing_charges_tenant_id", "billing_charges", ["tenant_id"])
    op.create_table(
        "wallet_ledger",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("wallets.tenant_id"), nullable=False),
        sa.Column("charge_id", sa.Uuid(), sa.ForeignKey("billing_charges.id")),
        sa.Column("event_key", sa.String(240), nullable=False),
        sa.Column("event", sa.String(24), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        *[
            sa.Column(name, sa.Integer(), nullable=False)
            for name in [
                "amount_cents",
                "paid_delta",
                "bonus_delta",
                "frozen_delta",
                "available_after_cents",
            ]
        ],
        *timestamps(),
        sa.UniqueConstraint("tenant_id", "event_key"),
    )
    op.create_index("ix_wallet_ledger_tenant_id", "wallet_ledger", ["tenant_id"])
    op.create_table(
        "provider_usage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("operation", sa.String(48), nullable=False),
        sa.Column("reference", sa.String(100)),
        sa.Column("model", sa.String(150), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("provider_request_id", sa.String(200)),
        sa.Column("error_code", sa.String(80)),
        sa.UniqueConstraint("tenant_id", "operation", "provider_request_id", "status"),
        *timestamps(),
    )
    op.create_index("ix_provider_usage_tenant_id", "provider_usage", ["tenant_id"])


def downgrade():
    for name in ["provider_usage", "wallet_ledger", "billing_charges", "wallets"]:
        op.drop_table(name)

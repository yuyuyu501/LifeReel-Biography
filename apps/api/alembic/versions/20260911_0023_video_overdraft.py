"""Allow authorized video holds and actual charges to exceed cash balance."""

from alembic import op

revision = "20260911_0023"
down_revision = "20260911_0022"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("wallets") as batch:
        batch.drop_constraint("nonnegative_balance", type_="check")
        batch.drop_constraint("covered_frozen", type_="check")
        batch.create_check_constraint("nonnegative_balance", "bonus_cents >= 0")
        batch.create_check_constraint("covered_frozen", "bonus_cents >= frozen_bonus_cents")


def downgrade():
    # Refuse rollback if outstanding debt/credit holds violate the old contract.
    # Never erase balances or release real reservations to force a downgrade.
    with op.batch_alter_table("wallets") as batch:
        batch.drop_constraint("nonnegative_balance", type_="check")
        batch.drop_constraint("covered_frozen", type_="check")
        batch.create_check_constraint("nonnegative_balance", "paid_cents >= 0 AND bonus_cents >= 0")
        batch.create_check_constraint(
            "covered_frozen",
            "paid_cents >= frozen_paid_cents AND bonus_cents >= frozen_bonus_cents",
        )

"""Add a transactional outbox for service boundary events."""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0036"
down_revision = "20260928_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_events_dispatch", "outbox_events", ["status", "occurred_at"])
    op.create_index("ix_outbox_events_tenant", "outbox_events", ["tenant_id", "occurred_at"])
    op.create_index("ix_outbox_events_tenant_id", "outbox_events", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_outbox_events_tenant_id", table_name="outbox_events")
    op.drop_index("ix_outbox_events_tenant", table_name="outbox_events")
    op.drop_index("ix_outbox_events_dispatch", table_name="outbox_events")
    op.drop_table("outbox_events")

"""Service inbox for durable cross-process job publication.

Revision ID: 20260929_0037
Revises: 20260928_0036
"""

import sqlalchemy as sa

from alembic import op

revision = "20260929_0037"
down_revision = "20260928_0036"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "job_deliveries",
        sa.Column(
            "job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Historical queued jobs predating the outbox must remain recoverable.
    op.execute(
        "INSERT INTO job_deliveries (job_id, event_id, tenant_id, delivered_at) "
        "SELECT id, id, tenant_id, CURRENT_TIMESTAMP FROM jobs "
        "WHERE status IN ('queued', 'running') AND NOT EXISTS "
        "(SELECT 1 FROM outbox_events WHERE aggregate_id = jobs.id)"
    )


def downgrade():
    op.drop_table("job_deliveries")

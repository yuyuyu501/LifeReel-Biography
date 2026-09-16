"""Durable, bounded worker leases."""

import sqlalchemy as sa

from alembic import op

revision = "20260914_0024"
down_revision = "20260911_0023"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("lease_token", sa.Uuid(), nullable=True))
    op.add_column("jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_jobs_dispatch", "jobs", ["kind", "status", "lease_expires_at", "created_at"]
    )


def downgrade():
    op.drop_index("ix_jobs_dispatch", table_name="jobs")
    op.drop_column("jobs", "lease_expires_at")
    op.drop_column("jobs", "lease_token")

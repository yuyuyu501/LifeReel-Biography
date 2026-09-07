"""link production runs to idempotent jobs

Revision ID: 20260828_0007
Revises: 20260828_0006
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_0007"
down_revision: str | None = "20260828_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("production_runs") as batch_op:
        batch_op.add_column(sa.Column("job_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_production_runs_job_id_jobs",
            "jobs",
            ["job_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_production_runs_job_id", "production_runs", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_production_runs_job_id", table_name="production_runs")
    with op.batch_alter_table("production_runs") as batch_op:
        batch_op.drop_constraint(
            "fk_production_runs_job_id_jobs", type_="foreignkey"
        )
        batch_op.drop_column("job_id")

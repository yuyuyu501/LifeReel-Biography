"""Scope evidence deduplication to the owning subject.

Revision ID: 20260904_0013
Revises: 20260903_0012
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260904_0013"
down_revision: str | None = "20260903_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_asset_tenant_sha256", "source_assets", type_="unique")
    op.create_unique_constraint(
        "uq_asset_tenant_subject_sha256",
        "source_assets",
        ["tenant_id", "subject_id", "sha256"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_asset_tenant_subject_sha256", "source_assets", type_="unique")
    op.create_unique_constraint(
        "uq_asset_tenant_sha256", "source_assets", ["tenant_id", "sha256"]
    )

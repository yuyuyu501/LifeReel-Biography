"""Store AI-derived relationships on memory entities.

Revision ID: 20260907_0018
Revises: 20260907_0017
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_0018"
down_revision: str | None = "20260907_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory_entities",
        sa.Column("relationship", sa.String(length=120), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE memory_entities SET relationship = CASE entity_type "
            "WHEN 'person' THEN '相关人物' "
            "WHEN 'place' THEN '相关地点' "
            "WHEN 'organization' THEN '相关组织' "
            "ELSE '相关记忆' END"
        )
    )
    op.alter_column("memory_entities", "relationship", nullable=False)


def downgrade() -> None:
    op.drop_column("memory_entities", "relationship")

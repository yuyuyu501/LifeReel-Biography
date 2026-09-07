"""Keep one active script per subject and review chapters independently.

Revision ID: 20260904_0014
Revises: 20260904_0013
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260904_0014"
down_revision: str | None = "20260904_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("script_scenes", sa.Column("chapter_id", sa.Uuid(), nullable=True))
    op.add_column(
        "script_scenes",
        sa.Column(
            "review_status",
            sa.String(length=32),
            nullable=False,
            server_default="needs_review",
        ),
    )
    op.add_column(
        "script_scenes", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_script_scenes_chapter_id_chapters",
        "script_scenes",
        "chapters",
        ["chapter_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_script_scenes_chapter_id", "script_scenes", ["chapter_id"])

    op.execute(
        sa.text(
            """
            UPDATE script_scenes AS scene
            SET review_status = CASE
                WHEN project.review_status = 'approved' THEN 'approved'
                WHEN project.review_status = 'rejected' THEN 'rejected'
                ELSE 'needs_review'
            END,
            locked_at = CASE
                WHEN project.review_status = 'approved' THEN project.locked_at
                ELSE NULL
            END
            FROM script_projects AS project
            WHERE project.id = scene.project_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY tenant_id, subject_id
                           ORDER BY created_at DESC, id DESC
                       ) AS row_number
                FROM script_projects
                WHERE status <> 'superseded'
            )
            UPDATE script_projects AS project
            SET status = 'superseded'
            FROM ranked
            WHERE project.id = ranked.id AND ranked.row_number > 1
            """
        )
    )
    op.create_index(
        "uq_script_project_active_subject",
        "script_projects",
        ["tenant_id", "subject_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'superseded'"),
    )


def downgrade() -> None:
    op.drop_index("uq_script_project_active_subject", table_name="script_projects")
    op.drop_index("ix_script_scenes_chapter_id", table_name="script_scenes")
    op.drop_constraint(
        "fk_script_scenes_chapter_id_chapters", "script_scenes", type_="foreignkey"
    )
    op.drop_column("script_scenes", "locked_at")
    op.drop_column("script_scenes", "review_status")
    op.drop_column("script_scenes", "chapter_id")

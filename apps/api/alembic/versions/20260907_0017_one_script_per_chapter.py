"""Keep exactly one current script document per chapter.

Revision ID: 20260907_0017
Revises: 20260907_0016
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_0017"
down_revision: str | None = "20260907_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TEMP TABLE script_scene_merge ON COMMIT DROP AS
            SELECT id AS source_id,
                   FIRST_VALUE(id) OVER (
                       PARTITION BY project_id, chapter_id
                       ORDER BY order_index, id
                   ) AS target_id
            FROM script_scenes
            WHERE chapter_id IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH merged AS (
                SELECT map.target_id,
                       STRING_AGG(scene.narration, E'\n\n' ORDER BY scene.order_index, scene.id)
                           AS narration,
                       STRING_AGG(
                           scene.visual_prompt,
                           E'\n\n'
                           ORDER BY scene.order_index, scene.id
                       ) AS visual_prompt,
                       LEAST(180, SUM(scene.duration_seconds)) AS duration_seconds,
                       CASE
                           WHEN BOOL_OR(scene.review_status = 'approved') THEN 'approved'
                           WHEN BOOL_OR(scene.review_status = 'rejected') THEN 'rejected'
                           ELSE 'needs_review'
                       END AS review_status,
                       MAX(scene.locked_at) AS locked_at
                FROM script_scene_merge AS map
                JOIN script_scenes AS scene ON scene.id = map.source_id
                GROUP BY map.target_id
            ), merged_claims AS (
                SELECT map.target_id,
                       JSON_AGG(DISTINCT claim.value) AS source_claim_ids
                FROM script_scene_merge AS map
                JOIN script_scenes AS scene ON scene.id = map.source_id
                CROSS JOIN LATERAL JSON_ARRAY_ELEMENTS_TEXT(scene.source_claim_ids) AS claim(value)
                GROUP BY map.target_id
            )
            UPDATE script_scenes AS target
            SET heading = COALESCE(
                    (SELECT title FROM chapters WHERE id = target.chapter_id),
                    target.heading
                ),
                narration = merged.narration,
                visual_prompt = merged.visual_prompt,
                duration_seconds = merged.duration_seconds,
                source_claim_ids = COALESCE(merged_claims.source_claim_ids, '[]'::JSON),
                review_status = merged.review_status,
                locked_at = CASE
                    WHEN merged.review_status = 'approved' THEN merged.locked_at
                    ELSE NULL
                END
            FROM merged
            LEFT JOIN merged_claims ON merged_claims.target_id = merged.target_id
            WHERE target.id = merged.target_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE script_shots AS shot
            SET scene_id = map.target_id
            FROM script_scene_merge AS map
            WHERE shot.scene_id = map.source_id
              AND map.source_id <> map.target_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM script_scenes AS scene
            USING script_scene_merge AS map
            WHERE scene.id = map.source_id
              AND map.source_id <> map.target_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH ordered AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY scene_id
                           ORDER BY order_index, id
                       ) AS next_index
                FROM script_shots
            )
            UPDATE script_shots AS shot
            SET order_index = ordered.next_index
            FROM ordered
            WHERE shot.id = ordered.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH ordered AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY project_id
                           ORDER BY order_index, id
                       ) AS next_index
                FROM script_scenes
            )
            UPDATE script_scenes AS scene
            SET order_index = ordered.next_index
            FROM ordered
            WHERE scene.id = ordered.id
            """
        )
    )
    op.create_unique_constraint(
        "uq_script_scene_project_chapter",
        "script_scenes",
        ["project_id", "chapter_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_script_scene_project_chapter",
        "script_scenes",
        type_="unique",
    )

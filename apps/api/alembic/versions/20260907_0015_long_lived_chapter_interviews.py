"""Keep one long-lived interview conversation per subject chapter.

Revision ID: 20260907_0015
Revises: 20260904_0014
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_0015"
down_revision: str | None = "20260904_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the latest session id so existing links continue to match the chapter card.
    op.execute(
        sa.text(
            """
            CREATE TEMP TABLE interview_session_merge ON COMMIT DROP AS
            SELECT id AS source_id,
                   FIRST_VALUE(id) OVER (
                       PARTITION BY tenant_id, subject_id, chapter_id
                       ORDER BY started_at DESC, id DESC
                   ) AS target_id
            FROM interview_sessions
            WHERE chapter_id IS NOT NULL
            """
        )
    )

    # Move every question and answer into one chronological conversation. Negative
    # temporary indexes avoid colliding with the existing per-session unique key.
    op.execute(
        sa.text(
            """
            WITH ordered_rounds AS (
                SELECT round_.id,
                       merge.target_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY merge.target_id
                           ORDER BY session.started_at,
                                    round_.round_index,
                                    round_.created_at,
                                    round_.id
                       ) AS merged_index
                FROM interview_rounds AS round_
                JOIN interview_sessions AS session ON session.id = round_.session_id
                JOIN interview_session_merge AS merge ON merge.source_id = session.id
            )
            UPDATE interview_rounds AS round_
            SET round_index = -ordered_rounds.merged_index
            FROM ordered_rounds
            WHERE round_.id = ordered_rounds.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE interview_rounds AS round_
            SET session_id = merge.target_id
            FROM interview_session_merge AS merge
            WHERE round_.session_id = merge.source_id
            """
        )
    )
    op.execute(
        sa.text(
            "UPDATE interview_rounds SET round_index = -round_index WHERE round_index < 0"
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE source_assets AS asset
            SET interview_session_id = merge.target_id
            FROM interview_session_merge AS merge
            WHERE asset.interview_session_id = merge.source_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE memory_claims AS claim
            SET interview_session_id = merge.target_id
            FROM interview_session_merge AS merge
            WHERE claim.interview_session_id = merge.source_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM interview_sessions AS session
            USING interview_session_merge AS merge
            WHERE session.id = merge.source_id
              AND merge.source_id <> merge.target_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE interview_sessions AS session
            SET round_count = counts.round_count
            FROM (
                SELECT session_id, COUNT(*) AS round_count
                FROM interview_rounds
                GROUP BY session_id
            ) AS counts
            WHERE session.id = counts.session_id
            """
        )
    )

    op.create_unique_constraint(
        "uq_interview_subject_chapter",
        "interview_sessions",
        ["tenant_id", "subject_id", "chapter_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_interview_subject_chapter",
        "interview_sessions",
        type_="unique",
    )

"""Durable realtime interview calls and separate speaker transcripts."""

import sqlalchemy as sa

from alembic import op

revision = "20260918_0030"
down_revision = "20260918_0029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "interview_voice_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("last_round_id", sa.Uuid()),
        sa.Column("source_asset_id", sa.Uuid()),
        sa.Column("workflow_id", sa.Uuid()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
    )
    for column in ("tenant_id", "session_id", "status"):
        op.create_index(f"ix_interview_voice_calls_{column}", "interview_voice_calls", [column])


def downgrade():
    op.drop_table("interview_voice_calls")

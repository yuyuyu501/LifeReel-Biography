"""Add platform identities and rotatable mini-program sessions."""

import sqlalchemy as sa

from alembic import op

revision = "20260924_0033"
down_revision = "20260923_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_identities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("app_id", sa.String(128), nullable=False),
        sa.Column("open_id", sa.String(128), nullable=False),
        sa.Column("union_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "platform", "app_id", "open_id", name="uq_platform_identity"
        ),
    )
    op.create_index(
        "ix_platform_identities_user_id", "platform_identities", ["user_id"]
    )
    op.create_index(
        "ix_platform_identities_tenant_id", "platform_identities", ["tenant_id"]
    )
    op.create_table(
        "mini_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_hash", sa.String(64), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["identity_id"], ["platform_identities.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("refresh_hash"),
    )
    op.create_index("ix_mini_sessions_identity_id", "mini_sessions", ["identity_id"])
    op.create_index("ix_mini_sessions_expires_at", "mini_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("mini_sessions")
    op.drop_table("platform_identities")

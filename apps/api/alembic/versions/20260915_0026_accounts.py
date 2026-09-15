"""Phone registration, account lifecycle and shared authentication throttles."""

import sqlalchemy as sa

from alembic import op

revision = "20260915_0026"
down_revision = "20260915_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_accounts") as batch:
        batch.alter_column("email", existing_type=sa.String(255), nullable=True)
        batch.add_column(sa.Column("phone", sa.String(20)))
        batch.add_column(
            sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.add_column(
            sa.Column("session_version", sa.Integer(), server_default="0", nullable=False)
        )
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True)))
        batch.create_index("ix_user_accounts_phone", ["phone"], unique=True)
    op.create_table(
        "account_phones",
        sa.Column("phone", sa.String(20), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user_accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_account_phones_user_id", "account_phones", ["user_id"])
    op.create_table(
        "sms_challenges",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sms_challenges_phone", "sms_challenges", ["phone"])
    op.create_index("ix_sms_challenges_expires_at", "sms_challenges", ["expires_at"])
    op.create_table(
        "auth_rate_limits",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("resets_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_rate_limits_resets_at", "auth_rate_limits", ["resets_at"])
    op.create_table(
        "account_audits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_account_audits_user_id", "account_audits", ["user_id"])
    from lifereel_api.core.config import get_settings

    settings = get_settings()
    if settings.bootstrap_owner_email:
        op.get_bind().execute(
            sa.text(
                "UPDATE user_accounts SET is_admin=true WHERE lower(email)=:email "
                "AND is_active=true AND deleted_at IS NULL AND id IN "
                "(SELECT user_id FROM tenant_memberships WHERE tenant_id=:tenant AND role='owner')"
            ).bindparams(sa.bindparam("tenant", type_=sa.Uuid())),
            {"email": settings.bootstrap_owner_email.lower(), "tenant": settings.default_tenant_id},
        )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM user_accounts "
                "WHERE phone IS NOT NULL OR deleted_at IS NOT NULL"
            )
        )
        .scalar()
    ):
        raise RuntimeError("ACCOUNT_MIGRATION_DOWNGRADE_REQUIRES_DATA_REVIEW")
    op.drop_table("account_phones")
    op.drop_table("account_audits")
    op.drop_table("auth_rate_limits")
    op.drop_table("sms_challenges")
    with op.batch_alter_table("user_accounts") as batch:
        batch.drop_index("ix_user_accounts_phone")
        for name in ("deleted_at", "session_version", "is_admin", "phone"):
            batch.drop_column(name)
        batch.alter_column("email", existing_type=sa.String(255), nullable=False)

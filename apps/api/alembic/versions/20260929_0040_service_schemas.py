"""Classify existing tables without copying data or media objects."""

import sqlalchemy as sa

from alembic import op

revision = "20260929_0040"
down_revision = "20260929_0039"
branch_labels = None
depends_on = None

# Frozen inventory: do not import evolving application metadata.
TABLES_BY_SCHEMA = {
    "identity": (
        "account_audits",
        "account_phones",
        "audit_events",
        "auth_rate_limits",
        "consent_grants",
        "mini_sessions",
        "persons",
        "platform_identities",
        "sms_challenges",
        "tenant_memberships",
        "tenants",
        "user_accounts",
    ),
    "interview": (
        "chapters",
        "interview_rounds",
        "interview_sessions",
        "interview_turn_workflows",
        "interview_voice_calls",
    ),
    "memory": ("memory_claims", "memory_conflicts", "memory_entities", "timeline_anchors"),
    "script": ("script_generation_receipts", "script_projects", "script_scenes", "script_shots"),
    "media": (
        "chapter_reference_packages",
        "evidence_observations",
        "evidence_uploads",
        "generated_assets",
        "production_runs",
        "publications",
        "restoration_photos",
        "source_assets",
        "transcript_segments",
        "transcript_versions",
        "transcripts",
    ),
    "billing": (
        "billing_charges",
        "billing_commands",
        "provider_usage",
        "recharge_orders",
        "wallet_ledger",
        "wallets",
    ),
    "tasks": ("job_deliveries", "jobs", "outbox_events"),
    "model_gateway": ("model_invocations",),
}


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for schema, tables in TABLES_BY_SCHEMA.items():
        op.execute(sa.schema.CreateSchema(schema, if_not_exists=True))
        for table in tables:
            op.execute(sa.text(f'ALTER TABLE public."{table}" SET SCHEMA "{schema}"'))


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for schema, tables in reversed(tuple(TABLES_BY_SCHEMA.items())):
        for table in reversed(tables):
            op.execute(sa.text(f'ALTER TABLE "{schema}"."{table}" SET SCHEMA public'))
        # RESTRICT preserves unrelated objects; never cascade away user data.
        op.execute(sa.schema.DropSchema(schema))

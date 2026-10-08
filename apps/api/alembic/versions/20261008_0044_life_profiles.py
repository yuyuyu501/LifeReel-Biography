"""Life profiles, independent book directories and saved manuscript adaptation."""

import sqlalchemy as sa

from alembic import op

revision = "20261008_0044"
down_revision = "20260930_0043"
branch_labels = None
depends_on = None


def upgrade():
    pg = op.get_bind().dialect.name == "postgresql"

    def schema(owner):
        return owner if pg else None

    def ref(name):
        return name if pg else ".".join(name.split(".")[-2:])

    def common():
        return [
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "tenant_id",
                sa.Uuid(),
                sa.ForeignKey(ref("identity.tenants.id"), ondelete="CASCADE"),
                nullable=False,
            ),
        ]

    op.create_table(
        "life_profiles",
        *common(),
        sa.Column(
            "subject_id",
            sa.Uuid(),
            sa.ForeignKey(ref("identity.persons.id"), ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("template_version", sa.String(80), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("readiness", sa.JSON(), nullable=False),
        sa.UniqueConstraint("tenant_id", "subject_id", name="uq_life_profile_subject"),
        schema=schema("interview"),
    )
    op.create_table(
        "life_profile_entries",
        *common(),
        sa.Column(
            "profile_id",
            sa.Uuid(),
            sa.ForeignKey(ref("interview.life_profiles.id"), ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_key", sa.String(100), nullable=False),
        sa.Column("record_key", sa.String(100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("certainty", sa.String(24), nullable=False),
        sa.Column("use_scope", sa.String(24), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("pseudonyms", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("profile_id", "field_key", "record_key", name="uq_profile_entry_key"),
        schema=schema("interview"),
    )
    op.create_table(
        "life_profile_revisions",
        *common(),
        sa.Column(
            "profile_id",
            sa.Uuid(),
            sa.ForeignKey(ref("interview.life_profiles.id"), ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.UniqueConstraint("profile_id", "version_number", name="uq_profile_revision_version"),
        sa.UniqueConstraint("profile_id", "request_id", name="uq_profile_revision_request"),
        schema=schema("interview"),
    )
    for table, columns in {
        "life_profiles": ["tenant_id", "subject_id"],
        "life_profile_entries": ["tenant_id", "profile_id"],
        "life_profile_revisions": ["tenant_id", "profile_id"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column], schema=schema("interview"))
    for owner, table, column, target in [
        ("interview", "interview_sessions", "profile_id", "interview.life_profiles.id"),
        ("memory", "memory_claims", "profile_entry_id", "interview.life_profile_entries.id"),
        ("book", "books", "profile_id", "interview.life_profiles.id"),
    ]:
        with op.batch_alter_table(table, schema=schema(owner)) as batch:
            batch.add_column(sa.Column(column, sa.Uuid(), nullable=True))
            parts = ref(target).split(".")
            batch.create_foreign_key(
                f"fk_{table}_{column}_{parts[-2]}",
                parts[-2],
                [column],
                [parts[-1]],
                referent_schema=parts[0] if pg else None,
                ondelete="SET NULL",
            )
            if table == "interview_sessions":
                batch.create_unique_constraint("uq_interview_life_profile", ["profile_id"])
    op.create_index(
        "ix_memory_claims_profile_entry_id",
        "memory_claims",
        ["profile_entry_id"],
        schema=schema("memory"),
    )
    with op.batch_alter_table("interview_turn_workflows", schema=schema("interview")) as batch:
        batch.add_column(
            sa.Column("profile_result", sa.JSON(), nullable=False, server_default="{}")
        )
    with op.batch_alter_table("books", schema=schema("book")) as batch:
        batch.add_column(
            sa.Column("directory_version", sa.Integer(), nullable=False, server_default="1")
        )
    with op.batch_alter_table("book_chapters", schema=schema("book")) as batch:
        batch.alter_column("chapter_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(
            sa.Column("title", sa.String(180), nullable=False, server_default="新章节")
        )
        batch.add_column(sa.Column("order_index", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(
            sa.Column("source_entry_ids", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("archived", sa.Boolean(), nullable=False, server_default="false")
        )
    book_prefix = "book." if pg else ""
    interview_prefix = "interview." if pg else ""
    op.execute(
        sa.text(
            f"UPDATE {book_prefix}book_chapters SET title = "
            f"(SELECT c.title FROM {interview_prefix}chapters c "
            "WHERE c.id = book_chapters.chapter_id), order_index = "
            f"(SELECT c.order_index FROM {interview_prefix}chapters c "
            "WHERE c.id = book_chapters.chapter_id) WHERE chapter_id IS NOT NULL"
        )
    )
    with op.batch_alter_table("script_projects", schema=schema("script")) as batch:
        batch.add_column(
            sa.Column("source_type", sa.String(24), nullable=False, server_default="legacy")
        )
        batch.add_column(
            sa.Column("source_snapshot", sa.JSON(), nullable=False, server_default="{}")
        )
    with op.batch_alter_table("script_generation_receipts", schema=schema("script")) as batch:
        batch.alter_column("project_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(
            sa.Column("status", sa.String(32), nullable=False, server_default="completed")
        )
        batch.add_column(sa.Column("checkpoint", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"

    def schema(owner):
        return owner if pg else None

    def table(owner, name):
        return f"{owner}.{name}" if pg else name

    checks = [
        f"SELECT count(*) FROM {table('interview', 'life_profiles')}",
        f"SELECT count(*) FROM {table('book', 'book_chapters')} WHERE chapter_id IS NULL",
        f"SELECT count(*) FROM {table('script', 'script_projects')} WHERE source_type = 'book'",
        f"SELECT count(*) FROM {table('script', 'script_generation_receipts')} "
        "WHERE project_id IS NULL",
    ]
    if any(bind.scalar(sa.text(query)) for query in checks):
        raise RuntimeError(
            "Life profile data exists; retain data and roll back compatible runtime images instead."
        )
    with op.batch_alter_table("script_generation_receipts", schema=schema("script")) as batch:
        batch.drop_column("checkpoint")
        batch.drop_column("status")
        batch.alter_column("project_id", existing_type=sa.Uuid(), nullable=False)
    with op.batch_alter_table("script_projects", schema=schema("script")) as batch:
        batch.drop_column("source_snapshot")
        batch.drop_column("source_type")
    with op.batch_alter_table("book_chapters", schema=schema("book")) as batch:
        for column in ["archived", "source_entry_ids", "order_index", "title"]:
            batch.drop_column(column)
        batch.alter_column("chapter_id", existing_type=sa.Uuid(), nullable=False)
    with op.batch_alter_table("books", schema=schema("book")) as batch:
        batch.drop_column("directory_version")
    with op.batch_alter_table("interview_turn_workflows", schema=schema("interview")) as batch:
        batch.drop_column("profile_result")
    op.drop_index(
        "ix_memory_claims_profile_entry_id", table_name="memory_claims", schema=schema("memory")
    )
    for owner, name, column, target in [
        ("book", "books", "profile_id", "life_profiles"),
        ("memory", "memory_claims", "profile_entry_id", "life_profile_entries"),
        ("interview", "interview_sessions", "profile_id", "life_profiles"),
    ]:
        with op.batch_alter_table(name, schema=schema(owner)) as batch:
            if name == "interview_sessions":
                batch.drop_constraint("uq_interview_life_profile", type_="unique")
            batch.drop_constraint(f"fk_{name}_{column}_{target}", type_="foreignkey")
            batch.drop_column(column)
    for name in ["life_profile_revisions", "life_profile_entries", "life_profiles"]:
        op.drop_table(name, schema=schema("interview"))

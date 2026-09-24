"""Add the foreign keys declared by the chapter asset models."""

from sqlalchemy import inspect

from alembic import op

revision = "20260924_0034"
down_revision = "20260924_0033"
branch_labels = None
depends_on = None


def _ensure_foreign_key(
    table: str,
    name: str,
    referred_table: str,
    local_columns: list[str],
    remote_columns: list[str],
) -> None:
    """Create the model foreign key while tolerating older repair migrations."""
    inspector = inspect(op.get_bind())
    existing = next(
        (
            foreign_key
            for foreign_key in inspector.get_foreign_keys(table)
            if foreign_key["name"] == name
        ),
        None,
    )
    if existing:
        options = existing.get("options") or {}
        matches = (
            existing.get("constrained_columns") == local_columns
            and existing.get("referred_table") == referred_table
            and existing.get("referred_columns") == remote_columns
            and options.get("ondelete", "").upper() == "SET NULL"
        )
        if matches:
            return
        op.drop_constraint(name, table, type_="foreignkey")

    op.create_foreign_key(
        name,
        table,
        referred_table,
        local_columns,
        remote_columns,
        ondelete="SET NULL",
    )


def upgrade() -> None:
    _ensure_foreign_key(
        "evidence_uploads",
        "fk_evidence_uploads_chapter_id_chapters",
        "chapters",
        ["chapter_id"],
        ["id"],
    )
    _ensure_foreign_key(
        "source_assets",
        "fk_source_assets_chapter_id_chapters",
        "chapters",
        ["chapter_id"],
        ["id"],
    )
    _ensure_foreign_key(
        "source_assets",
        "fk_source_assets_derived_from_asset_id_source_assets",
        "source_assets",
        ["derived_from_asset_id"],
        ["id"],
    )


def downgrade() -> None:
    with op.batch_alter_table("source_assets") as batch:
        batch.drop_constraint(
            "fk_source_assets_derived_from_asset_id_source_assets", type_="foreignkey"
        )
        batch.drop_constraint("fk_source_assets_chapter_id_chapters", type_="foreignkey")
    with op.batch_alter_table("evidence_uploads") as batch:
        batch.drop_constraint("fk_evidence_uploads_chapter_id_chapters", type_="foreignkey")

"""Add the foreign keys declared by the chapter asset models."""

from alembic import op

revision = "20260924_0034"
down_revision = "20260924_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("evidence_uploads") as batch:
        batch.create_foreign_key(
            "fk_evidence_uploads_chapter_id_chapters",
            "chapters",
            ["chapter_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("source_assets") as batch:
        batch.create_foreign_key(
            "fk_source_assets_chapter_id_chapters",
            "chapters",
            ["chapter_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_source_assets_derived_from_asset_id_source_assets",
            "source_assets",
            ["derived_from_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("source_assets") as batch:
        batch.drop_constraint(
            "fk_source_assets_derived_from_asset_id_source_assets", type_="foreignkey"
        )
        batch.drop_constraint("fk_source_assets_chapter_id_chapters", type_="foreignkey")
    with op.batch_alter_table("evidence_uploads") as batch:
        batch.drop_constraint("fk_evidence_uploads_chapter_id_chapters", type_="foreignkey")

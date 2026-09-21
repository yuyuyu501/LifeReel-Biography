"""Restore foreign keys for chapter-scoped evidence references."""

from alembic import op

revision = "20260921_0031"
down_revision = "20260918_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Old databases may contain references written while these columns had no
    # constraints. Preserve the assets and clear only references that cannot
    # be resolved before enforcing the model's SET NULL contract.
    op.execute(
        """
        UPDATE source_assets
        SET chapter_id = NULL
        WHERE chapter_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM chapters WHERE chapters.id = source_assets.chapter_id)
        """
    )
    op.execute(
        """
        UPDATE source_assets
        SET derived_from_asset_id = NULL
        WHERE derived_from_asset_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM source_assets parent
              WHERE parent.id = source_assets.derived_from_asset_id
          )
        """
    )
    op.execute(
        """
        UPDATE evidence_uploads
        SET chapter_id = NULL
        WHERE chapter_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM chapters WHERE chapters.id = evidence_uploads.chapter_id
          )
        """
    )
    op.create_foreign_key(
        "fk_source_assets_chapter_id_chapters",
        "source_assets",
        "chapters",
        ["chapter_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_source_assets_derived_from_asset_id_source_assets",
        "source_assets",
        "source_assets",
        ["derived_from_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_evidence_uploads_chapter_id_chapters",
        "evidence_uploads",
        "chapters",
        ["chapter_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    for name, table in (
        ("fk_evidence_uploads_chapter_id_chapters", "evidence_uploads"),
        ("fk_source_assets_derived_from_asset_id_source_assets", "source_assets"),
        ("fk_source_assets_chapter_id_chapters", "source_assets"),
    ):
        op.drop_constraint(name, table, type_="foreignkey")

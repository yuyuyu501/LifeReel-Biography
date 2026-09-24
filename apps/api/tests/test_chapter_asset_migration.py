"""Exercise 0031 against PostgreSQL in a transaction-local disposable schema."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_chapter_asset_foreign_keys_preserve_rows_and_enforce_references():
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("MIGRATION_TEST_DATABASE_URL must point to an isolated PostgreSQL database")
    engine = create_engine(url)
    assert engine.dialect.name == "postgresql"
    path = (
        Path(__file__).parents[1]
        / "alembic/versions/20260924_0034_chapter_asset_foreign_keys.py"
    )
    spec = importlib.util.spec_from_file_location("chapter_asset_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = f"migration_test_{uuid4().hex}"
    chapter, parent, child, orphan, upload, orphan_upload, missing = [uuid4() for _ in range(7)]
    try:
        with engine.connect() as connection, connection.begin() as transaction:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(text("CREATE TABLE chapters (id uuid PRIMARY KEY)"))
            connection.execute(text("""
                CREATE TABLE source_assets (
                    id uuid PRIMARY KEY, chapter_id uuid, derived_from_asset_id uuid,
                    original_filename text NOT NULL
                )
            """))
            connection.execute(text("""
                CREATE TABLE evidence_uploads (
                    id uuid PRIMARY KEY, chapter_id uuid, original_filename text NOT NULL
                )
            """))
            connection.execute(text("INSERT INTO chapters VALUES (:id)"), {"id": chapter})
            connection.execute(text("""
                INSERT INTO source_assets VALUES (:id, :chapter, :parent, :filename)
            """), [
                {"id": parent, "chapter": chapter, "parent": None, "filename": "parent.jpg"},
                {"id": child, "chapter": chapter, "parent": parent, "filename": "child.jpg"},
                {"id": orphan, "chapter": None, "parent": None, "filename": "orphan.jpg"},
            ])
            connection.execute(text("""
                INSERT INTO evidence_uploads VALUES (:id, :chapter, :filename)
            """), [
                {"id": upload, "chapter": chapter, "filename": "upload.jpg"},
                {"id": orphan_upload, "chapter": None, "filename": "orphan-upload.jpg"},
            ])
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()

                assert connection.execute(text("""
                    SELECT chapter_id, derived_from_asset_id, original_filename
                    FROM source_assets WHERE id = :id
                """), {"id": orphan}).one() == (None, None, "orphan.jpg")
                assert connection.execute(text("""
                    SELECT chapter_id, original_filename FROM evidence_uploads WHERE id = :id
                """), {"id": orphan_upload}).one() == (None, "orphan-upload.jpg")
                assert connection.execute(text("""
                    SELECT chapter_id, derived_from_asset_id FROM source_assets WHERE id = :id
                """), {"id": child}).one() == (chapter, parent)
                for table, expected_count in (("source_assets", 3), ("evidence_uploads", 2)):
                    count = connection.scalar(text(f"SELECT count(*) FROM {table}"))
                    assert count == expected_count

                for table, column, row_id in (
                    ("source_assets", "chapter_id", child),
                    ("source_assets", "derived_from_asset_id", child),
                    ("evidence_uploads", "chapter_id", upload),
                ):
                    with pytest.raises(IntegrityError), connection.begin_nested():
                        connection.execute(
                            text(f"UPDATE {table} SET {column} = :missing WHERE id = :id"),
                            {"missing": missing, "id": row_id},
                        )

                connection.execute(text("DELETE FROM chapters WHERE id = :id"), {"id": chapter})
                assert connection.scalar(text(
                    "SELECT count(*) FROM source_assets WHERE chapter_id IS NOT NULL"
                )) == 0
                assert connection.scalar(text(
                    "SELECT count(*) FROM evidence_uploads WHERE chapter_id IS NOT NULL"
                )) == 0
                connection.execute(text("DELETE FROM source_assets WHERE id = :id"), {"id": parent})
                assert connection.execute(text("""
                    SELECT derived_from_asset_id, original_filename
                    FROM source_assets WHERE id = :id
                """), {"id": child}).one() == (None, "child.jpg")

                migration.downgrade()
                assert inspect(connection).get_foreign_keys("source_assets") == []
                assert inspect(connection).get_foreign_keys("evidence_uploads") == []
                migration.upgrade()
                assert len(inspect(connection).get_foreign_keys("source_assets")) == 2
                assert len(inspect(connection).get_foreign_keys("evidence_uploads")) == 1
            # Roll back the schema and all synthetic rows even after a passing run.
            transaction.rollback()
    finally:
        engine.dispose()

"""Verify channel backfill and rollback protection in an isolated PostgreSQL schema."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from lifereel_api.core.database import Base


def test_recharge_channel_migration_preserves_history_and_guards_rollback():
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("MIGRATION_TEST_DATABASE_URL must point to isolated PostgreSQL")
    engine = create_engine(url)
    assert engine.dialect.name == "postgresql"
    path = Path(__file__).parents[1] / "alembic/versions/20260928_0035_recharge_payment_method.py"
    spec = importlib.util.spec_from_file_location("recharge_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = f"recharge_test_{uuid4().hex}"
    try:
        with engine.connect() as connection, connection.begin() as transaction:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(text("""
                CREATE TABLE recharge_orders (
                    id integer PRIMARY KEY, status text NOT NULL, amount_cents integer NOT NULL,
                    verified_reference text UNIQUE
                )
            """))
            connection.execute(text("""
                INSERT INTO recharge_orders VALUES (1, 'credited', 100, 'OLD123456'),
                    (2, 'pending', 250, NULL)
            """))
            context = MigrationContext.configure(
                connection, opts={"target_metadata": Base.metadata}
            )
            with Operations.context(context):
                migration.upgrade()
                assert connection.execute(text("""
                    SELECT id,status,amount_cents,verified_reference,payment_method
                    FROM recharge_orders ORDER BY id
                """)).all() == [
                    (1, "credited", 100, "OLD123456", "wechat"),
                    (2, "pending", 250, None, "wechat"),
                ]
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(text("""
                        UPDATE recharge_orders SET payment_method='unknown' WHERE id=2
                    """))
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(text("""
                        UPDATE recharge_orders SET payment_method=NULL WHERE id=2
                    """))
                connection.execute(text("""
                    INSERT INTO recharge_orders VALUES (3, 'pending', 1, NULL, 'alipay')
                """))
                with pytest.raises(RuntimeError, match="Alipay orders exist"):
                    migration.downgrade()
                assert connection.scalar(text("SELECT count(*) FROM recharge_orders")) == 3
                connection.execute(text("DELETE FROM recharge_orders WHERE id=3"))
                migration.downgrade()
                assert "payment_method" not in {
                    column["name"] for column in inspect(connection).get_columns("recharge_orders")
                }
                migration.upgrade()
                assert connection.scalar(text("""
                    SELECT count(*) FROM recharge_orders WHERE payment_method='wechat'
                """)) == 2
            transaction.rollback()
    finally:
        engine.dispose()

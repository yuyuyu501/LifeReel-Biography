"""Single-database namespace migration; synthetic data, no external providers.

SCHEMA_TEST_DATABASE_URL must name an isolated PostgreSQL database containing
'test' in its name. Tests create and remove their own UUID-named databases.
"""

import hashlib
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, inspect, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from lifereel_api.core.config import get_settings
from lifereel_api.core.database import Base, engine
from lifereel_api.core.schema import SERVICE_SCHEMAS, SQLITE_SCHEMA_MAP
from lifereel_api.modules.billing.models import Wallet
from lifereel_api.modules.evidence.models import SourceAsset
from lifereel_api.modules.identity.models import Person, Tenant
from lifereel_api.modules.interview.models import Chapter
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.modules.script.models import ScriptProject
from lifereel_api.providers.models import ModelInvocation

API = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "schema_migration", API / "alembic/versions/20260929_0040_service_schemas.py"
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
OWNERS = {
    table: schema for schema, tables in migration.TABLES_BY_SCHEMA.items() for table in tables
}


def test_all_models_match_frozen_schema_inventory():
    # 0040 stays frozen; newly owned tables are added by the later book migration.
    current_owners = {**OWNERS, **dict.fromkeys(
        ("books", "book_chapters", "book_revisions"), "book"
    )}
    assert set(SERVICE_SCHEMAS) == set(migration.TABLES_BY_SCHEMA) | {"book"}
    assert {table.name: table.schema for table in Base.metadata.tables.values()} == current_owners
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.target_fullname.count(".") == 2
            assert foreign_key.column.table.schema == current_owners[foreign_key.column.table.name]
    assert SourceAsset.__table__.c.storage_key.type.length == 512


def test_sqlite_translation_keeps_cross_service_foreign_keys():
    targets = {item["referred_table"] for item in inspect(engine).get_foreign_keys("source_assets")}
    assert {"tenants", "persons", "interview_sessions", "chapters", "source_assets"} <= targets


@pytest.fixture
def postgres(monkeypatch):
    raw = os.environ.get("SCHEMA_TEST_DATABASE_URL")
    if not raw:
        if os.environ.get("SCHEMA_REQUIRE_POSTGRES") == "1":
            pytest.fail("SCHEMA_REQUIRE_POSTGRES=1 requires SCHEMA_TEST_DATABASE_URL")
        pytest.skip("SCHEMA_TEST_DATABASE_URL must identify an isolated PostgreSQL database")
    url = make_url(raw)
    assert url.get_backend_name() == "postgresql" and "test" in (url.database or "").lower()
    name = "lifereel_schema_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    target_url = url.set(database=name)
    target = create_engine(target_url)
    # Embedded migrations must not run the CLI logging setup and disable the
    # application's loggers in subsequent tests. Connection settings are
    # supplied by get_settings below; the script path is explicit.
    config = Config()
    config.set_main_option("script_location", str(API / "alembic"))
    monkeypatch.setattr(
        get_settings(), "database_url", target_url.render_as_string(hide_password=False)
    )
    try:
        yield target, config
    finally:
        target.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


def snapshot(target, relocated):
    result = {}
    with target.connect() as connection:
        for table, owner in OWNERS.items():
            schema = owner if relocated else "public"
            rows = list(
                connection.scalars(
                    text(
                        f'SELECT to_jsonb(t)::text FROM "{schema}"."{table}" t '
                        "ORDER BY to_jsonb(t)::text"
                    )
                )
            )
            oid = connection.scalar(
                text("SELECT to_regclass(:name)::oid"), {"name": f"{schema}.{table}"}
            )
            indexes = connection.execute(
                text(
                    "SELECT indexrelid, indisunique, indisvalid FROM pg_index "
                    "WHERE indrelid=:oid ORDER BY indexrelid"
                ),
                {"oid": oid},
            ).all()
            constraints = connection.execute(
                text(
                    "SELECT oid, conname, contype, confrelid, confdeltype, convalidated "
                    "FROM pg_constraint WHERE conrelid=:oid ORDER BY oid"
                ),
                {"oid": oid},
            ).all()
            result[table] = (
                oid,
                len(rows),
                hashlib.sha256(chr(10).join(rows).encode()).hexdigest(),
                indexes,
                constraints,
            )
    return result


def assert_layout(target, relocated, revision=None):
    with target.connect() as connection:
        for table, owner in OWNERS.items():
            actual = connection.scalar(
                text(
                    "SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE c.relkind='r' AND c.relname=:name"
                ),
                {"name": table},
            )
            assert actual == (owner if relocated else "public"), table
        version = connection.scalar(text("SELECT version_num FROM public.alembic_version"))
        assert version == (revision or ("20260929_0040" if relocated else "20260929_0039"))


def test_empty_postgresql_upgrade_and_model_check(postgres):
    target, config = postgres
    command.upgrade(config, "head")
    assert_layout(target, True, ScriptDirectory.from_config(config).get_current_head())
    command.check(config)
    command.upgrade(config, "head")
    with target.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE public.qa_unrelated (id integer)")
    command.check(config)  # Autogenerate must ignore unmanaged tables.


def test_populated_postgresql_migration_preserves_data_constraints_and_rollback(postgres):
    target, config = postgres
    command.upgrade(config, "20260929_0039")
    old = target.execution_options(schema_translate_map=SQLITE_SCHEMA_MAP)
    with Session(old) as db:
        tenant = Tenant(name="Schema QA", slug="schema-" + uuid4().hex)
        db.add(tenant)
        db.flush()
        person = Person(tenant_id=tenant.id, display_name="Synthetic person")
        chapter = Chapter(tenant_id=tenant.id, order_index=1, title="Synthetic chapter")
        db.add_all([person, chapter])
        db.flush()
        asset = SourceAsset(
            tenant_id=tenant.id,
            subject_id=person.id,
            chapter_id=chapter.id,
            kind="photo",
            original_filename="synthetic.png",
            mime_type="image/png",
            byte_size=17,
            sha256="a" * 64,
            storage_key="LifeReel-Biography/schema-test/synthetic.png",
        )
        db.add_all(
            [
                asset,
                Wallet(tenant_id=tenant.id, paid_cents=1234, bonus_cents=56),
                ScriptProject(tenant_id=tenant.id, subject_id=person.id, title="Synthetic script"),
                Job(
                    tenant_id=tenant.id,
                    kind="qa.schema",
                    status="succeeded",
                    payload={"synthetic": True},
                ),
                ModelInvocation(
                    tenant_id=tenant.id,
                    operation="qa",
                    request_digest="b" * 64,
                    state="succeeded",
                    response={"synthetic": True},
                ),
            ]
        )
        # Freeze this fixture to the pre-0040 columns; current ORM may grow new fields.
        db.execute(
            text("""INSERT INTO public.memory_claims
            (id, tenant_id, subject_id, chapter_id, claim_text, source_quote,
             claim_type, confidence, review_status, extraction_provider, created_at, updated_at)
            VALUES (:id, :tenant, :subject, :chapter, 'Synthetic fact', 'Synthetic quote',
                    'recollection', 1, 'unreviewed', 'rule', now(), now())"""),
            {"id": uuid4(), "tenant": tenant.id, "subject": person.id, "chapter": chapter.id},
        )
        db.commit()
        tenant_id, chapter_id, asset_id = tenant.id, chapter.id, asset.id
    before = snapshot(target, False)
    assert all(
        any(before[name][1] for name in tables) for tables in migration.TABLES_BY_SCHEMA.values()
    )

    # A destination collision must abort atomically, without partially moved tables.
    with target.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA identity")
        connection.exec_driver_sql("CREATE TABLE identity.persons (id integer)")
    with pytest.raises(SQLAlchemyError):
        command.upgrade(config, "20260929_0040")
    assert snapshot(target, False) == before
    with target.begin() as connection:
        connection.exec_driver_sql("DROP TABLE identity.persons")
        connection.exec_driver_sql("DROP SCHEMA identity")

    command.upgrade(config, "20260929_0040")
    assert_layout(target, True)
    assert snapshot(target, True) == before
    with pytest.raises(IntegrityError), target.begin() as connection:
        connection.execute(
            update(SourceAsset).where(SourceAsset.id == asset_id).values(chapter_id=uuid4())
        )
    with target.connect() as connection:
        transaction = connection.begin()
        connection.execute(delete(Chapter).where(Chapter.id == chapter_id))
        assert (
            connection.scalar(select(SourceAsset.chapter_id).where(SourceAsset.id == asset_id))
            is None
        )
        assert connection.scalar(select(MemoryClaim.chapter_id)) is None
        assert (
            connection.scalar(select(Wallet.paid_cents).where(Wallet.tenant_id == tenant_id))
            == 1234
        )
        assert connection.scalar(select(SourceAsset.storage_key)) == asset.storage_key
        transaction.rollback()

    # Do not delete unrelated objects on downgrade, even after moving earlier schemas.
    with target.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE memory.qa_keep (id integer)")
    with pytest.raises(SQLAlchemyError):
        command.downgrade(config, "20260929_0039")
    assert_layout(target, True)
    assert snapshot(target, True) == before
    with target.begin() as connection:
        connection.exec_driver_sql("DROP TABLE memory.qa_keep")
    command.downgrade(config, "20260929_0039")
    assert_layout(target, False)
    assert snapshot(target, False) == before
    with Session(old) as db:
        assert db.get(Wallet, tenant_id).paid_cents == 1234
    command.upgrade(config, "20260929_0040")
    assert snapshot(target, True) == before
    command.upgrade(config, "head")
    command.check(config)

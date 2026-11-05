"""Organization write safety on an explicitly isolated local PostgreSQL database."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from lifereel_api.modules.identity.models import Person, Tenant
from lifereel_api.modules.interview import profile_service
from lifereel_api.modules.interview.profile_models import LifeProfileRevision
from lifereel_api.modules.interview.profile_schemas import ProfilePatch
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from lifereel_api.core.database import Base
from lifereel_api.core.errors import ApiError
from lifereel_api.core.schema import SERVICE_SCHEMAS


@pytest.fixture
def isolated():
    url = os.environ.get("INTERVIEW_TEST_DATABASE_URL")
    if not url:
        pytest.skip("INTERVIEW_TEST_DATABASE_URL must name a disposable local PostgreSQL database")
    parsed = make_url(url)
    assert parsed.database == "interview_hybrid_test" and parsed.host in {"localhost", "127.0.0.1"}
    assert parsed.get_backend_name() == "postgresql"
    engine = create_engine(url, connect_args={"options": "-c lock_timeout=5000"})
    schema = f"organization_test_{uuid4().hex}"
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = engine.execution_options(
        schema_translate_map={None: schema, **dict.fromkeys(SERVICE_SCHEMAS, schema)},
    )
    factory = sessionmaker(bind=scoped, expire_on_commit=False)
    try:
        Base.metadata.create_all(scoped)
        with factory() as db:
            tenant = Tenant(name="Synthetic organization QA", slug=str(uuid4()))
            db.add(tenant)
            db.flush()
            person = Person(tenant_id=tenant.id, display_name="合成并发人物")
            db.add(person)
            db.flush()
            profile = profile_service.ensure(db, tenant.id, person.id)
            db.commit()
            yield factory, tenant.id, profile.id
    finally:
        scoped.dispose()
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def test_two_concurrent_writes_cannot_overwrite_each_other(isolated):
    factory, tenant, profile_id = isolated
    with factory() as db:
        initial_revisions = db.scalar(select(func.count()).select_from(LifeProfileRevision))
    barrier = Barrier(2)

    def write(year):
        with factory() as db:
            snapshot = profile_service.read(db, tenant, profile_id)
            db.commit()  # retain a stale identity map, as a waiting worker can do
            barrier.wait(timeout=10)
            try:
                result = profile_service.patch(db, tenant, profile_id, ProfilePatch(
                    expected_version=snapshot["version_number"],
                    changes=[{"field_key": "identity.birth_time", "value": year}],
                ))
                return result["version_number"]
            except ApiError as exc:
                db.rollback()
                assert exc.status_code == 409
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(write, ["1970年", "1971年"]))
    assert results.count("conflict") == 1
    with factory() as db:
        entries = profile_service.read(db, tenant, profile_id)["entries"]
        assert len([e for e in entries if e["field_key"] == "identity.birth_time"]) == 1
        assert (
            db.scalar(select(func.count()).select_from(LifeProfileRevision))
            == initial_revisions + 1
        )


def test_failed_organization_transaction_rolls_back_then_replays_once(isolated, monkeypatch):
    factory, tenant, profile_id = isolated
    original = profile_service.enqueue_sync
    with factory() as db:
        snapshot = profile_service.read(db, tenant, profile_id)
        initial_revisions = db.scalar(select(func.count()).select_from(LifeProfileRevision))
    payload = ProfilePatch(
        expected_version=snapshot["version_number"],
        changes=[
            {"field_key": "work.records[]", "record_key": "job", "value": {"what": "整理档案"}},
            {"field_key": "identity.birth_time", "value": "1970年"},
        ],
    )

    def fail(*args):
        raise RuntimeError("synthetic outbox failure")

    monkeypatch.setattr(profile_service, "enqueue_sync", fail)
    with factory() as db:
        with pytest.raises(RuntimeError, match="synthetic outbox failure"), db.begin():
            profile_service.patch(db, tenant, profile_id, payload, commit=False)
    with factory() as db:
        restored = profile_service.read(db, tenant, profile_id)
        assert restored["version_number"] == snapshot["version_number"]
        assert not any(e["field_key"] in {"work.records[]", "identity.birth_time"}
                       for e in restored["entries"])
        assert db.scalar(select(func.count()).select_from(LifeProfileRevision)) == initial_revisions
    monkeypatch.setattr(profile_service, "enqueue_sync", original)
    with factory() as db:
        accepted = profile_service.patch(db, tenant, profile_id, payload)
        replay = profile_service.patch(db, tenant, profile_id, payload)
        assert accepted["version_number"] == replay["version_number"]
        assert (
            db.scalar(select(func.count()).select_from(LifeProfileRevision))
            == initial_revisions + 1
        )

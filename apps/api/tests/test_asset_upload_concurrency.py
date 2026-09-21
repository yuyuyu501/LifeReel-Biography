"""D01 regressions: real independent transactions and synthetic, local objects only.

Run PostgreSQL cases by setting EVIDENCE_TEST_DATABASE_URL to an explicitly isolated
PostgreSQL database. Each case creates/removes its own UUID-named schema. No container
is started, no existing schema is changed, and no remote storage/provider is contacted.

CI (from apps/api): set EVIDENCE_TEST_DATABASE_URL and EVIDENCE_REQUIRE_POSTGRES=1,
then run `python -m pytest tests/test_asset_upload_concurrency.py -k postgresql -v`.
The required flag makes a missing PostgreSQL URL fail instead of silently skipping.
"""

import asyncio
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier, Event, Lock
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from botocore.response import StreamingBody
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.datastructures import Headers

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import Base, get_db
from lifereel_api.core.errors import ApiError, install_error_handlers
from lifereel_api.core.models import utcnow
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.modules.evidence import direct_uploads, service
from lifereel_api.modules.evidence.asset_conflicts import is_asset_duplicate
from lifereel_api.modules.evidence.models import EvidenceUpload, SourceAsset
from lifereel_api.modules.evidence.router import router
from lifereel_api.modules.evidence.storage import LocalPrivateStorage
from lifereel_api.modules.identity.models import Person, Tenant
from lifereel_api.modules.interview.models import Chapter, InterviewSession

CONTENT = b"D01 synthetic evidence, identical bytes across every request."


@pytest.fixture(params=["sqlite", "postgresql"])
def upload_db(request, tmp_path):
    schema = None
    if request.param == "postgresql":
        url = os.environ.get("EVIDENCE_TEST_DATABASE_URL")
        if not url:
            if os.environ.get("EVIDENCE_REQUIRE_POSTGRES") == "1":
                pytest.fail("EVIDENCE_REQUIRE_POSTGRES=1 requires EVIDENCE_TEST_DATABASE_URL")
            pytest.skip("EVIDENCE_TEST_DATABASE_URL must name an isolated PostgreSQL database")
        engine = create_engine(url, connect_args={"options": "-c statement_timeout=15000"})
        assert engine.dialect.name == "postgresql"
        schema = f"evidence_test_{uuid4().hex}"
        with engine.begin() as conn:
            assert conn.get_isolation_level() == "READ COMMITTED"
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine = engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = create_engine(
            f"sqlite:///{(tmp_path / 'uploads.db').as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 15},
        )

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    tables = [model.__table__ for model in (
        Tenant, Person, Chapter, InterviewSession, SourceAsset, EvidenceUpload,
    )]
    try:
        Base.metadata.create_all(engine, tables=tables)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        if schema:
            with engine.begin() as conn:
                conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


@pytest.fixture
def scope(upload_db):
    tenant, other_tenant, person, other_person, foreign_person = [uuid4() for _ in range(5)]
    chapters, sessions = [uuid4(), uuid4()], [uuid4(), uuid4()]
    with upload_db() as db:
        db.add_all([
            Tenant(id=tenant, name="D01", slug=str(tenant)),
            Tenant(id=other_tenant, name="Other D01", slug=str(other_tenant)),
        ])
        db.flush()
        db.add_all([
            Person(id=person, tenant_id=tenant, display_name="First"),
            Person(id=other_person, tenant_id=tenant, display_name="Second"),
            Person(id=foreign_person, tenant_id=other_tenant, display_name="Foreign"),
            *[Chapter(id=chapter, tenant_id=tenant, order_index=i, title=f"Chapter {i}")
              for i, chapter in enumerate(chapters)],
        ])
        db.flush()
        db.add_all([
            InterviewSession(id=session, tenant_id=tenant, subject_id=person, chapter_id=chapter)
            for session, chapter in zip(sessions, chapters, strict=True)
        ])
        db.commit()
    return SimpleNamespace(
        tenant=tenant, other_tenant=other_tenant, person=person, other_person=other_person,
        foreign_person=foreign_person, chapters=chapters, sessions=sessions,
    )


@pytest.fixture
def storage(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "local_storage_path", str(tmp_path / "objects"))
    local = LocalPrivateStorage()
    calls, lock = [], Lock()
    put = local.put_file

    def record(key, file):
        with lock:
            calls.append(key)
        put(key, file)

    monkeypatch.setattr(local, "put_file", record)
    monkeypatch.setattr(service, "private_storage", lambda: local)
    return SimpleNamespace(local=local, calls=calls)


def racing_sessions(upload_db, count):
    barrier = Barrier(count, timeout=15)

    class RacingSession(Session):
        def scalar(self, statement, *args, **kwargs):
            result = super().scalar(statement, *args, **kwargs)
            if (
                statement.column_descriptions[0].get("entity") is SourceAsset
                and not self.info.get("dedup_checked")
            ):
                self.info["dedup_checked"] = True
                # Force every request past a genuinely empty lookup before any insert.
                assert result is None
                barrier.wait()
            return result

    return sessionmaker(
        bind=upload_db.kw["bind"], class_=RacingSession, autoflush=False, expire_on_commit=False,
    )


def create(db, scope, *, filename="memory.txt", session=None, **changes):
    values = dict(
        tenant_id=scope.tenant, subject_id=scope.person, interview_session_id=session,
        kind="document", consent_scope="private",
    )
    values.update(changes)
    with BytesIO(CONTENT) as file:
        upload = UploadFile(
            file=file, filename=filename, headers=Headers({"content-type": "text/plain"}),
        )
        return asyncio.run(service.create_asset(db, upload=upload, **values))


@pytest.mark.parametrize("variant", ["same-key", "different-suffix", "different-chapter"])
def test_parallel_http_uploads_return_one_asset_and_write_once(upload_db, scope, storage, variant):
    count = 6
    sessions = racing_sessions(upload_db, count)
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    install_error_handlers(app)

    def dependency():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    app.dependency_overrides[get_tenant_id] = lambda: scope.tenant

    def request(i):
        form = {
            "subject_id": str(scope.person), "kind": "document",
            "consent_scope": "family" if i % 2 else "private",
        }
        if variant == "different-chapter" and i % 3:
            form["interview_session_id"] = str(scope.sessions[i % 3 - 1])
        filename = (
            f"copy-{i}.{'md' if i % 2 else 'txt'}"
            if variant == "different-suffix" else "memory.txt"
        )
        # Separate portals model separate API event loops; one shared portal would
        # serialize the synchronous DB/storage section and never reproduce D01.
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.post(
                "/v1/evidence/assets", data=form, files={"file": (filename, CONTENT, "text/plain")},
            )

    with ThreadPoolExecutor(max_workers=count) as pool:
        responses = list(pool.map(request, range(count)))
    assert [r.status_code for r in responses] == [201] * count
    assert len({r.json()["id"] for r in responses}) == 1
    with upload_db() as db:
        assets = list(db.scalars(select(SourceAsset)))
        assert len(assets) == 1
        asset = assets[0]
        assert all(r.json()["chapter_id"] == (str(asset.chapter_id) if asset.chapter_id else None)
                   for r in responses)
        assert all(r.json()["original_filename"] == asset.original_filename for r in responses)
        assert all(r.json()["consent_scope"] == asset.consent_scope for r in responses)
        assert asset.sha256 == hashlib.sha256(CONTENT).hexdigest()
        assert storage.local.get(asset.storage_key) == CONTENT
        assert storage.calls == [asset.storage_key]
    assert len([p for p in storage.local.root.rglob("*") if p.is_file()]) == 1


def test_concurrent_dedup_stays_within_tenant_and_person(upload_db, scope, storage):
    owners = [
        (scope.tenant, scope.person), (scope.tenant, scope.other_person),
        (scope.other_tenant, scope.foreign_person),
    ] * 2
    sessions = racing_sessions(upload_db, len(owners))

    def request(owner):
        with sessions() as db:
            asset = create(db, scope, tenant_id=owner[0], subject_id=owner[1])
            return asset.id, asset.tenant_id, asset.subject_id

    with ThreadPoolExecutor(max_workers=len(owners)) as pool:
        results = list(pool.map(request, owners))
    assert len({item[0] for item in results}) == 3
    assert [(item[1], item[2]) for item in results] == owners
    assert len(storage.calls) == 3
    with upload_db() as db:
        for asset in db.scalars(select(SourceAsset)):
            assert f"tenants/{asset.tenant_id}/persons/{asset.subject_id}/" in asset.storage_key
            assert storage.local.get(asset.storage_key) == CONTENT


def test_retries_preserve_first_metadata_and_still_validate_scope(upload_db, scope, storage):
    with upload_db() as db:
        first = create(db, scope, session=scope.sessions[0], filename="first.TXT")
        for session in (None, scope.sessions[1]):
            duplicate = create(
                db, scope, session=session, filename="renamed.md", consent_scope="public",
            )
            assert duplicate.id == first.id
            assert duplicate.chapter_id == scope.chapters[0]
            assert duplicate.interview_session_id == scope.sessions[0]
            assert duplicate.original_filename == "first.TXT"
            assert duplicate.consent_scope == "private"
            assert duplicate.storage_key.endswith("original.txt")
        for changes in (
            {"tenant_id": scope.other_tenant},
            {"subject_id": scope.other_person, "session": scope.sessions[0]},
            {"session": uuid4()},
        ):
            with pytest.raises(ApiError):
                create(db, scope, **changes)
    assert len(storage.calls) == 1


@pytest.mark.parametrize("after_write", [False, True])
def test_storage_failure_rolls_back_asset_preserves_caller_and_allows_retry(
    upload_db, scope, storage, monkeypatch, after_write,
):
    put = storage.local.put_file
    delete = Mock(side_effect=AssertionError("A shared object must never be deleted"))
    monkeypatch.setattr(storage.local, "delete", delete)

    def fail(key, file):
        if after_write:
            put(key, file)
        raise OSError("synthetic object write failure")

    monkeypatch.setattr(storage.local, "put_file", fail)
    with upload_db() as db:
        db.get(Person, scope.person).preferred_name = "Unrelated caller change"
        with pytest.raises(OSError, match="synthetic"):
            create(db, scope)
        assert db.is_active
        assert db.scalar(select(SourceAsset)) is None
        db.commit()
    with upload_db() as db:
        assert db.get(Person, scope.person).preferred_name == "Unrelated caller change"
        monkeypatch.setattr(storage.local, "put_file", put)
        asset = create(db, scope)
        assert storage.local.get(asset.storage_key) == CONTENT
    delete.assert_not_called()


def test_failed_writer_releases_competing_uploads(upload_db, scope, storage, monkeypatch):
    sessions = racing_sessions(upload_db, 3)
    put, lock, attempts = storage.local.put_file, Lock(), []

    def fail_first(key, file):
        with lock:
            attempts.append(key)
            first = len(attempts) == 1
        put(key, file)
        if first:
            raise OSError("synthetic failure after writing the shared object")

    monkeypatch.setattr(storage.local, "put_file", fail_first)

    def request(_):
        with sessions() as db:
            try:
                return create(db, scope).id
            except OSError:
                assert db.is_active
                return None

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(request, range(3)))
    assert results.count(None) == 1
    assert len(set(results) - {None}) == 1
    assert len(attempts) == 2
    with upload_db() as db:
        asset, = db.scalars(select(SourceAsset))
        assert storage.local.get(asset.storage_key) == CONTENT


def test_asset_is_not_visible_until_object_write_finishes(upload_db, scope, storage, monkeypatch):
    started, release, contender_insert = Event(), Event(), Event()
    put = storage.local.put_file

    def slow_put(key, file):
        started.set()
        assert release.wait(15)
        put(key, file)

    monkeypatch.setattr(storage.local, "put_file", slow_put)

    def before_insert(conn, cursor, statement, parameters, context, executemany):
        if (
            started.is_set() and statement.startswith("INSERT INTO")
            and "source_assets" in statement
        ):
            contender_insert.set()

    engine = upload_db.kw["bind"]
    event.listen(engine, "before_cursor_execute", before_insert)

    def request():
        with upload_db() as db:
            return create(db, scope).id

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(request)
            try:
                assert started.wait(15)
                second = pool.submit(request)
                assert contender_insert.wait(15)
                with upload_db() as db:
                    assert db.scalar(select(SourceAsset)) is None
                assert not second.done()
            finally:
                release.set()
            assert first.result(timeout=20) == second.result(timeout=20)
    finally:
        event.remove(engine, "before_cursor_execute", before_insert)
    assert len(storage.calls) == 1


@pytest.mark.parametrize("variant", ["same-key", "different-chapter-and-suffix"])
def test_relay_and_direct_upload_converge(upload_db, scope, storage, monkeypatch, variant):
    # An in-memory S3 double provides atomic object PUT/COPY without network calls.
    objects, lock = {}, Lock()

    def put(key, file):
        content = file.read()
        with lock:
            objects[key] = content

    monkeypatch.setattr(storage.local, "put_file", put)
    client = Mock()
    client.head_object.return_value = {
        "ContentLength": len(CONTENT), "ContentType": "text/plain", "ETag": '"verified"',
    }
    client.get_object.side_effect = lambda **kwargs: {
        "Body": StreamingBody(BytesIO(CONTENT), len(CONTENT)),
    }
    client.copy_object.side_effect = lambda **kwargs: put(kwargs["Key"], BytesIO(CONTENT))
    remote = SimpleNamespace(client=client, bucket="synthetic-bucket")
    with upload_db() as db:
        upload = EvidenceUpload(
            tenant_id=scope.tenant, subject_id=scope.person, kind="document",
            original_filename="direct.md" if variant != "same-key" else "memory.txt",
            chapter_id=scope.chapters[1] if variant != "same-key" else None,
            interview_session_id=scope.sessions[1] if variant != "same-key" else None,
            mime_type="text/plain", byte_size=len(CONTENT), consent_scope="family",
            storage_key=f"synthetic-staging/{uuid4()}", expires_at=utcnow(),
        )
        db.add(upload)
        db.commit()
        upload_id, staging_key = upload.id, upload.storage_key
    sessions = racing_sessions(upload_db, 2)

    def request(direct):
        with sessions() as db:
            asset = (
                direct_uploads.verify_and_commit(
                    db, scope.tenant, db.get(EvidenceUpload, upload_id), remote,
                ) if direct else create(db, scope)
            )
            return asset.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request, [False, True]))
    assert results[0] == results[1]
    with upload_db() as db:
        asset, = db.scalars(select(SourceAsset))
        assert db.get(EvidenceUpload, upload_id).asset_id == asset.id
        assert objects[asset.storage_key] == CONTENT
        assert asset.sha256 == hashlib.sha256(CONTENT).hexdigest()
    client.delete_object.assert_called_once_with(Bucket="synthetic-bucket", Key=staging_key)


def test_storage_key_conflict_without_matching_identity_is_not_hidden(upload_db, scope, storage):
    with upload_db() as db:
        existing = create(db, scope)
        existing.sha256 = "0" * 64
        db.commit()
        with pytest.raises(IntegrityError):
            create(db, scope)
        assert db.is_active
        assert db.scalar(select(SourceAsset)).id == existing.id
    assert len(storage.calls) == 1


def miss_first_asset_lookup(monkeypatch, db):
    scalar = db.scalar
    checked = False

    def stale_lookup(statement, *args, **kwargs):
        nonlocal checked
        result = scalar(statement, *args, **kwargs)
        if statement.column_descriptions[0].get("entity") is SourceAsset and not checked:
            checked = True
            return None
        return result

    monkeypatch.setattr(db, "scalar", stale_lookup)


@pytest.mark.parametrize("constraint", [
    "uq_source_assets_storage_key", "uq_asset_tenant_subject_sha256",
])
def test_both_unique_constraints_recover_without_losing_caller_changes(
    upload_db, scope, storage, monkeypatch, constraint,
):
    engine = upload_db.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL constraint ordering and transaction semantics")
    if constraint == "uq_source_assets_storage_key":
        # Model production installations where storage_key's index predates the
        # subject-scoped hash index, so the same-key race raises that constraint.
        schema = engine.get_execution_options()["schema_translate_map"][None]
        with engine.begin() as conn:
            conn.exec_driver_sql(
                f'ALTER TABLE "{schema}".source_assets '
                'DROP CONSTRAINT uq_asset_tenant_subject_sha256'
            )
            conn.exec_driver_sql(
                f'ALTER TABLE "{schema}".source_assets ADD CONSTRAINT '
                'uq_asset_tenant_subject_sha256 UNIQUE (tenant_id, subject_id, sha256)'
            )
    with upload_db() as db:
        first = create(db, scope)
        first_id = first.id
    seen = []

    def observe(error):
        seen.append(error.orig.diag.constraint_name)
        return is_asset_duplicate(error)

    monkeypatch.setattr(service, "is_asset_duplicate", observe)
    with upload_db() as db:
        miss_first_asset_lookup(monkeypatch, db)
        db.get(Person, scope.person).preferred_name = "Caller change survives conflict"
        duplicate = create(db, scope)
        assert duplicate.id == first_id
        assert db.is_active
        db.commit()
    with upload_db() as db:
        assert db.get(Person, scope.person).preferred_name == "Caller change survives conflict"
    assert seen == [constraint]
    assert len(storage.calls) == 1


def test_unrelated_integrity_error_is_not_hidden_by_existing_asset(
    upload_db, scope, storage, monkeypatch,
):
    with upload_db() as db:
        first = create(db, scope)
        first_id = first.id
        miss_first_asset_lookup(monkeypatch, db)

        def invalid_asset(mapper, connection, target):
            target.kind = None  # A NOT NULL error must not be treated as a duplicate.

        event.listen(SourceAsset, "before_insert", invalid_asset)
        try:
            with pytest.raises(IntegrityError) as exc:
                create(db, scope)
            assert not is_asset_duplicate(exc.value)
            assert db.is_active
            assert db.scalar(select(SourceAsset)).id == first_id
        finally:
            event.remove(SourceAsset, "before_insert", invalid_asset)
    assert len(storage.calls) == 1


def test_commit_failure_keeps_object_and_allows_retry(
    upload_db, scope, storage, monkeypatch,
):
    if upload_db.kw["bind"].dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL outer transaction semantics")
    delete = Mock(side_effect=AssertionError("Do not delete a shared object"))
    monkeypatch.setattr(storage.local, "delete", delete)
    with upload_db() as db:
        commit = db.commit
        monkeypatch.setattr(db, "commit", Mock(side_effect=OSError("synthetic commit failure")))
        with pytest.raises(OSError, match="synthetic commit failure"):
            create(db, scope)
        assert db.is_active
        assert db.scalar(select(SourceAsset)) is None
        assert storage.local.get(storage.calls[0]) == CONTENT
        monkeypatch.setattr(db, "commit", commit)
        asset = create(db, scope)
        assert storage.local.get(asset.storage_key) == CONTENT
    delete.assert_not_called()

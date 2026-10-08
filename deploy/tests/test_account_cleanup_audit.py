"""Real PostgreSQL safety checks in a disposable, unmounted Docker database."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Column, ForeignKey, Table, Uuid, create_engine, event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateSchema

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api/src"))
spec = importlib.util.spec_from_file_location(
    "account_cleanup_audit", ROOT / "deploy/account_cleanup_audit.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


@pytest.fixture(scope="module")
def database():
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker required for isolated PostgreSQL boundary tests")
    name = "lifereel-account-audit-test-" + uuid4().hex[:12]
    result = subprocess.run(
        [
            docker,
            "run",
            "--detach",
            "--name",
            name,
            "--pull=never",
            "--label",
            "lifereel.purpose=account-audit-isolated-test",
            "--env",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "--env",
            "POSTGRES_DB=account_audit_test",
            "--publish",
            "127.0.0.1::5432",
            "--tmpfs",
            "/var/lib/postgresql/data",
            "pgvector/pgvector:pg16",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        pytest.fail("Unable to start isolated PostgreSQL container; details redacted")
    engine = None
    try:
        port = (
            subprocess.run(
                [docker, "port", name, "5432/tcp"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            .stdout.strip()
            .rsplit(":", 1)[1]
        )
        url = f"postgresql+psycopg://postgres@127.0.0.1:{port}/account_audit_test"
        engine = create_engine(url, echo=False)
        deadline = time.monotonic() + 30
        while True:
            try:
                with engine.connect() as connection:
                    connection.exec_driver_sql("SELECT 1")
                break
            except DBAPIError:
                if time.monotonic() > deadline:
                    pytest.fail("Isolated PostgreSQL startup timeout")
                time.sleep(0.2)
        # Import declarations only. Application startup, provider clients and seed hooks never run.
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "sqlite:///:memory:"
        try:
            for name_module in (
                "auth.models",
                "identity.models",
                "governance.models",
                "interview.models",
                "interview.profile_models",
                "memory.models",
                "script.models",
                "book.models",
                "evidence.models",
                "restoration.models",
                "production.models",
                "production.reference_models",
                "publication.models",
                "billing.models",
                "jobs.models",
                "jobs.events",
            ):
                importlib.import_module("lifereel_api.modules." + name_module)
            importlib.import_module("lifereel_api.providers.models")
            from lifereel_api.core.database import Base
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous
        with engine.begin() as connection:
            for schema in audit.SCHEMA_TABLES:
                connection.execute(CreateSchema(schema))
            Base.metadata.create_all(connection)
        with engine.connect() as connection:
            metadata = audit.reflect_database(connection)
        assert set(metadata.tables) == audit.EXPECTED_TABLES
        yield engine, metadata, url
    finally:
        if engine:
            engine.dispose()
        # Exact container created by this fixture, with no host data mounts.
        subprocess.run([docker, "rm", "--force", name], capture_output=True, timeout=15, check=True)


@pytest.fixture
def data(database):
    engine, _, url = database
    with engine.connect() as connection:
        with connection.begin():
            metadata = audit.reflect_database(connection)
            owner, other, tenant, foreign, person, other_person, asset = [uuid4() for _ in range(7)]

            def insert(table_name, **values):
                connection.execute(metadata.tables[table_name].insert().values(**values))

            now = datetime.now(UTC)
            for identifier, email in ((owner, audit.TARGET_EMAIL), (other, "other@example.test")):
                insert(
                    "identity.user_accounts",
                    id=identifier,
                    email=email,
                    display_name="Test",
                    password_hash="isolated-test-login-marker",
                    is_active=True,
                    is_admin=False,
                    session_version=0,
                    created_at=now,
                    updated_at=now,
                )
            for identifier in (tenant, foreign):
                insert(
                    "identity.tenants",
                    id=identifier,
                    name="Test",
                    slug=identifier.hex,
                    created_at=now,
                )
            for tenant_id, user_id in ((tenant, owner), (foreign, other)):
                insert(
                    "identity.tenant_memberships",
                    id=uuid4(),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    role="owner",
                    created_at=now,
                    updated_at=now,
                )
                insert(
                    "billing.wallets",
                    tenant_id=tenant_id,
                    paid_cents=0,
                    bonus_cents=100,
                    frozen_paid_cents=0,
                    frozen_bonus_cents=0,
                    token_remainder_nano=17,
                    created_at=now,
                    updated_at=now,
                )
            for identifier, tenant_id in ((person, tenant), (other_person, foreign)):
                insert(
                    "identity.persons",
                    id=identifier,
                    tenant_id=tenant_id,
                    display_name="Test",
                    is_subject=True,
                    is_minor=False,
                    created_at=now,
                    updated_at=now,
                )
            key = f"LifeReel-Biography/tenants/{tenant}/persons/{person}/asset.bin"

            def source(identifier=asset, tenant_id=tenant, subject_id=person, **extra):
                insert(
                    "media.source_assets",
                    id=identifier,
                    tenant_id=tenant_id,
                    subject_id=subject_id,
                    kind="document",
                    original_filename="test.bin",
                    mime_type="application/octet-stream",
                    byte_size=1,
                    sha256=identifier.hex * 2,
                    storage_key=extra.pop("storage_key", key),
                    status="ready",
                    consent_scope="private",
                    consent_status="unknown",
                    analysis_status="completed",
                    metadata={},
                    captured_at=now,
                    created_at=now,
                    updated_at=now,
                    **extra,
                )

            def job(tenant_id=tenant, **extra):
                insert(
                    "tasks.jobs",
                    id=uuid4(),
                    tenant_id=tenant_id,
                    kind="test.mock",
                    status=extra.pop("status", "completed"),
                    payload={},
                    attempt_count=0,
                    created_at=now,
                    updated_at=now,
                    **extra,
                )

            source()
            values = dict(
                connection=connection,
                metadata=metadata,
                owner=owner,
                other=other,
                tenant=tenant,
                foreign=foreign,
                person=person,
                other_person=other_person,
                asset=asset,
                key=key,
                now=now,
                insert=insert,
                source=source,
                job=job,
                url=url,
            )
            yield values
            connection.rollback()


def run(data):
    return audit.audit_database(data["connection"], data["metadata"])


def codes(report):
    return {item["code"] for item in report["blockers"]}


def test_exclusive_scope_preserves_login_and_wallet_without_writing(data):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(data["connection"], "before_cursor_execute", capture)
    try:
        report = run(data)
    finally:
        event.remove(data["connection"], "before_cursor_execute", capture)
    assert not report["blockers"]
    assert report["scope_tenant_ids"] == [str(data["tenant"])]
    assert report["tables"]["identity.persons"]["scope"] == 1
    assert report["tables"]["identity.persons"]["total"] == 2
    assert report["tables"]["billing.wallets"]["action"] == "zero_existing_wallet"
    assert "billing.wallets" not in report["review_delete_order"]
    assert report["tables"]["identity.user_accounts"]["action"] == "preserve"
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert all("password_hash" not in statement for statement in statements)
    assert "isolated-test-login-marker" not in json.dumps(report)


def test_shared_member_blocks_entire_tenant(data):
    data["insert"](
        "identity.tenant_memberships",
        id=uuid4(),
        tenant_id=data["tenant"],
        user_id=data["other"],
        role="viewer",
        created_at=data["now"],
        updated_at=data["now"],
    )
    report = run(data)
    assert "SHARED_OR_NONOWNER_TENANT" in codes(report)
    assert report["scope_tenant_ids"] == []
    assert all(t["scope"] == 0 for t in report["tables"].values())


def test_other_platform_identity_blocks_tenant_without_membership(data):
    data["insert"](
        "identity.platform_identities",
        id=uuid4(),
        tenant_id=data["tenant"],
        user_id=data["other"],
        platform="test",
        app_id="test",
        open_id="test",
        created_at=data["now"],
        updated_at=data["now"],
    )
    assert "SHARED_OR_NONOWNER_TENANT" in codes(run(data))


@pytest.mark.parametrize("ondelete", ["CASCADE", "SET NULL", "RESTRICT"])
def test_external_foreign_key_cannot_delete_or_modify_other_tenant(data, ondelete):
    extra = Table(
        "external_reference",
        data["metadata"],
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid),
        Column("asset_id", Uuid, ForeignKey("media.source_assets.id", ondelete=ondelete)),
        schema="public",
    )
    extra.create(data["connection"])
    data["connection"].execute(
        extra.insert().values(id=uuid4(), tenant_id=data["foreign"], asset_id=data["asset"])
    )
    report = run(data)
    assert "UNREVIEWED_SCHEMA" in codes(report)
    assert any(
        item["code"] == "EXTERNAL_FOREIGN_KEY_REFERENCE" and item["ondelete"] == ondelete
        for item in report["blockers"]
    )


def test_self_reference_is_allowed_but_other_tenant_self_reference_is_blocked(data):
    data["source"](
        identifier=uuid4(),
        storage_key=data["key"] + ".derived",
        derived_from_asset_id=data["asset"],
    )
    assert not run(data)["blockers"]
    data["source"](
        identifier=uuid4(),
        tenant_id=data["foreign"],
        subject_id=data["other_person"],
        storage_key=f"LifeReel-Biography/tenants/{data['foreign']}/foreign.bin",
        derived_from_asset_id=data["asset"],
    )
    assert "EXTERNAL_FOREIGN_KEY_REFERENCE" in codes(run(data))


def test_json_shared_object_and_unconstrained_uuid_reference_are_blocked(data):
    data["job"](
        tenant_id=data["foreign"],
        result={"nested": [{"storage_key": data["key"]}], "person_id": str(data["person"])},
    )
    report = run(data)
    assert {"EXTERNAL_JSON_REFERENCE", "SHARED_OR_UNSAFE_OBJECT"} <= codes(report)
    assert report["objects"][0]["shared"]
    assert not report["objects"][0]["eligible_candidate"]


@pytest.mark.parametrize(
    "kind",
    [
        "running_job",
        "live_lease",
        "pending_outbox",
        "frozen_wallet",
        "uncertain_invocation",
        "unknown_job_state",
    ],
)
def test_active_and_uncertain_states_block(data, kind):
    if kind == "running_job":
        data["job"](status="running")
    elif kind == "unknown_job_state":
        data["job"](status="new-unreviewed-status")
    elif kind == "live_lease":
        data["job"](lease_expires_at=data["now"] + timedelta(hours=1))
    elif kind == "pending_outbox":
        data["insert"](
            "tasks.outbox_events",
            id=uuid4(),
            tenant_id=data["tenant"],
            event_type="profile.sync.requested",
            schema_version=1,
            aggregate_id=data["person"],
            payload={},
            status="pending",
            occurred_at=data["now"],
        )
    elif kind == "frozen_wallet":
        wallet = data["metadata"].tables["billing.wallets"]
        data["connection"].execute(
            wallet.update()
            .where(wallet.c.tenant_id == data["tenant"])
            .values(frozen_bonus_cents=10)
        )
    else:
        data["insert"](
            "model_gateway.model_invocations",
            id=uuid4(),
            tenant_id=data["tenant"],
            operation="test",
            request_digest="0" * 64,
            state="uncertain",
            created_at=data["now"],
        )
    assert {"ACTIVE_OR_UNSETTLED_ROW", "FROZEN_WALLET"} & codes(run(data))


def test_account_audits_select_subject_never_administrator_actor(data):
    for user_id, actor_id in ((data["owner"], data["other"]), (data["other"], data["owner"])):
        data["insert"](
            "identity.account_audits",
            id=uuid4(),
            user_id=user_id,
            actor_id=actor_id,
            action="test",
            changes={},
            created_at=data["now"],
            updated_at=data["now"],
        )
    report = run(data)
    assert report["tables"]["identity.account_audits"]["scope"] == 1
    assert report["tables"]["identity.account_audits"]["total"] == 2


def test_postgresql_readonly_transaction_rejects_mutation(database):
    engine, metadata, _ = database
    with engine.connect() as connection:
        with connection.begin():
            connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            with pytest.raises(DBAPIError) as captured:
                connection.execute(metadata.tables["identity.tenants"].delete())
            assert captured.value.orig.sqlstate == "25006"


@pytest.mark.parametrize(
    "suffix",
    [
        "../foreign.bin",
        "%2e%2e/foreign.bin",
        "x\\foreign.bin",
        "//foreign.bin",
        "./foreign.bin",
        "%2e%2e%2fforeign.bin",
    ],
)
def test_object_key_boundary_rejects_traversal(suffix):
    tenant = str(uuid4())
    assert not audit.key_in_scope(f"LifeReel-Biography/tenants/{tenant}/{suffix}", [tenant])


def test_object_prefix_is_uuid_segment_exact():
    tenant = str(uuid4())
    assert not audit.key_in_scope(f"LifeReel-Biography/tenants/{tenant}-other/file", [tenant])
    assert audit.key_in_scope(f"{tenant}/interview-voice/file.wav", [tenant])


@pytest.mark.parametrize(
    "template",
    ["{tenant}/interview-voice/{file}.wav", "LifeReel-Biography/evidence/{tenant}/{file}.md"],
)
def test_confirmed_legacy_prefixes_require_exact_tenant_and_find_json_references(template):
    tenant, foreign, file_id = str(uuid4()), str(uuid4()), str(uuid4())
    key = template.format(tenant=tenant, file=file_id)
    assert audit.key_in_scope(key, [tenant])
    assert not audit.key_in_scope(key, [foreign])
    assert not audit.key_in_scope(
        template.format(tenant=tenant + "-foreign", file=file_id), [tenant]
    )
    assert audit.json_references({"nested": [key]})[0] == {key}
    assert audit.json_references({"url": "https://isolated.example.test/" + key})[0] == {key}


def test_storage_audit_owns_orphans_but_retains_versions_and_shared_keys():
    tenant = str(uuid4())
    prefix = f"LifeReel-Biography/tenants/{tenant}/"
    known, shared, orphan = [prefix + name for name in ("known.bin", "shared.bin", "orphan.bin")]
    calls = []

    class MetadataOnlyClient:
        def get_paginator(self, operation):
            assert operation in {
                "list_objects_v2",
                "list_object_versions",
                "list_multipart_uploads",
            }
            calls.append(operation)

            class Paginator:
                def paginate(self, **kwargs):
                    if kwargs["Prefix"] != prefix:
                        return [{}]
                    if operation == "list_objects_v2":
                        return [
                            {
                                "Contents": [
                                    {"Key": key, "Size": 1} for key in (known, shared, orphan)
                                ]
                            }
                        ]
                    if operation == "list_object_versions":
                        return [{"Versions": [{"Key": known, "VersionId": "old"}]}]
                    return [{"Uploads": [{"Key": orphan, "UploadId": "pending"}]}]

            return Paginator()

        def get_bucket_versioning(self, **_kwargs):
            return {"Status": "Enabled"}

    report = {
        "scope_tenant_ids": [tenant],
        "blockers": [],
        "objects": [
            {"key": known, "eligible_candidate": True},
            {"key": shared, "eligible_candidate": False},
        ],
    }
    audit.audit_storage(report, MetadataOnlyClient(), "isolated-test-bucket")
    objects = {obj["key"]: obj for obj in report["storage"]["objects"]}
    assert objects[known]["eligible_candidate"]
    assert objects[orphan]["eligible_candidate"]
    assert not objects[shared]["eligible_candidate"]
    assert report["storage"]["versions"][0]["review_only"]
    assert "MULTIPART_UPLOADS_REQUIRE_REVIEW" in codes(report)
    assert set(calls) == {"list_objects_v2", "list_object_versions", "list_multipart_uploads"}


def test_cache_audit_does_not_clear_shared_queue_or_foreign_cache(tmp_path):
    tenant, foreign = str(uuid4()), str(uuid4())

    class ReadonlyRedis:
        def scan_iter(self, *, match, count):
            assert match == f"lifereel:voice-revision:{tenant}:*"
            return []

        def llen(self, _queue):
            return 2

        def lrange(self, _queue, start, end):
            return [
                json.dumps({"tenant_id": tenant, "job_id": "target"}),
                json.dumps({"tenant_id": foreign, "job_id": "foreign"}),
            ]

    report = {"scope_tenant_ids": [tenant], "blockers": []}
    audit.audit_cache(report, ReadonlyRedis(), tmp_path, "shared-queue")
    assert report["cache"]["target_queue_items"] == [{"tenant_id": tenant, "job_id": "target"}]
    assert "TARGET_ITEMS_IN_SHARED_QUEUE" in codes(report)


def test_local_cache_does_not_follow_ancestor_symlink_into_foreign_tenant(tmp_path):
    tenant = str(uuid4())
    other = tmp_path / "foreign"
    other.mkdir()
    (other / tenant).mkdir()
    (other / tenant / "private.bin").write_bytes(b"isolated-test")
    project = tmp_path / "LifeReel-Biography"
    project.mkdir()
    try:
        (project / "tenants").symlink_to(other, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires Windows developer mode or privileges")

    class EmptyRedis:
        def scan_iter(self, **_kwargs):
            return []

        def llen(self, _queue):
            return 0

    report = {"scope_tenant_ids": [tenant], "blockers": []}
    audit.audit_cache(report, EmptyRedis(), tmp_path, "shared-queue")
    assert report["cache"]["tenant_local_files"] == []
    assert "LOCAL_PATH_REQUIRES_REVIEW" in codes(report)

"""Exercise the actual reset against isolated PostgreSQL and synthetic media."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

pytest_plugins = ["test_account_cleanup_audit"]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy"))
spec = importlib.util.spec_from_file_location("account_cleanup", ROOT / "deploy/account_cleanup.py")
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


def count(connection, table, **values):
    return connection.scalar(
        select(func.count())
        .select_from(table)
        .where(*(table.c[key] == value for key, value in values.items()))
    )


def test_reset_removes_target_records_but_keeps_both_accounts_and_other_tenant(data):
    data["source"](
        identifier=uuid4(),
        storage_key=data["key"] + ".derived",
        derived_from_asset_id=data["asset"],
    )
    for user, actor in ((data["owner"], data["other"]), (data["other"], data["owner"])):
        data["insert"](
            "identity.account_audits",
            id=uuid4(),
            user_id=user,
            actor_id=actor,
            action="test",
            changes={},
            created_at=data["now"],
            updated_at=data["now"],
        )
    connection, metadata = data["connection"], data["metadata"]
    before = cleanup.preserved_hashes(connection, metadata, [data["tenant"]], data["owner"])
    result = cleanup.reset_database(connection, metadata, str(data["owner"]), [str(data["tenant"])])
    assert result["target_business_rows_remaining"] == 0
    assert before == cleanup.preserved_hashes(connection, metadata, [data["tenant"]], data["owner"])
    assert count(connection, metadata.tables["identity.persons"], tenant_id=data["tenant"]) == 0
    assert count(connection, metadata.tables["media.source_assets"], tenant_id=data["tenant"]) == 0
    assert count(connection, metadata.tables["identity.persons"], tenant_id=data["foreign"]) == 1
    assert count(connection, metadata.tables["identity.user_accounts"]) == 2
    assert count(connection, metadata.tables["identity.account_audits"], user_id=data["other"]) == 1
    wallets = metadata.tables["billing.wallets"]
    target = (
        connection.execute(select(wallets).where(wallets.c.tenant_id == data["tenant"]))
        .mappings()
        .one()
    )
    assert all(target[field] == 0 for field in cleanup.BALANCES)
    assert (
        connection.scalar(
            select(wallets.c.bonus_cents).where(wallets.c.tenant_id == data["foreign"])
        )
        == 100
    )


@pytest.mark.parametrize("changed", ["account", "scope", "shared"])
def test_reset_rejects_changed_ownership_without_deleting(data, changed):
    account, scope = str(data["owner"]), [str(data["tenant"])]
    if changed == "account":
        account = str(data["other"])
    elif changed == "scope":
        scope = [str(data["foreign"])]
    else:
        data["insert"](
            "identity.tenant_memberships",
            id=uuid4(),
            tenant_id=data["tenant"],
            user_id=data["other"],
            role="viewer",
            created_at=data["now"],
            updated_at=data["now"],
        )
    with pytest.raises(RuntimeError):
        cleanup.reset_database(data["connection"], data["metadata"], account, scope)
    assert count(data["connection"], data["metadata"].tables["identity.persons"]) == 2
    assert count(data["connection"], data["metadata"].tables["media.source_assets"]) == 1


def test_postcheck_failure_rolls_back_deletions_and_wallet_changes(data, monkeypatch):
    real = cleanup.preserved_hashes
    calls = 0

    def changed_snapshot(*args):
        nonlocal calls
        calls += 1
        return real(*args) if calls == 1 else {"simulated_failure": "changed"}

    monkeypatch.setattr(cleanup, "preserved_hashes", changed_snapshot)
    with pytest.raises(RuntimeError, match="PRESERVED_ACCOUNT_OR_OTHER_TENANT_CHANGED"):
        with data["connection"].begin_nested():
            cleanup.reset_database(
                data["connection"], data["metadata"], str(data["owner"]), [str(data["tenant"])]
            )
    assert count(data["connection"], data["metadata"].tables["identity.persons"]) == 2
    assert count(data["connection"], data["metadata"].tables["media.source_assets"]) == 1
    wallet = data["metadata"].tables["billing.wallets"]
    assert (
        data["connection"].scalar(
            select(wallet.c.bonus_cents).where(wallet.c.tenant_id == data["tenant"])
        )
        == 100
    )


def test_media_backup_downloads_exact_owned_keys_and_hashes_bytes(tmp_path):
    tenant = str(uuid4())
    key = f"LifeReel-Biography/tenants/{tenant}/synthetic.txt"
    content = b"private synthetic QA object"
    calls = []

    class Storage:
        def get_object(self, **params):
            calls.append(params)
            return {"Body": io.BytesIO(content), "ETag": '"qa-etag"'}

    report = {
        "scope_tenant_ids": [tenant],
        "storage": {
            "versioning": "Disabled",
            "multipart_uploads": [],
            "objects": [
                {"key": key, "bytes": len(content), "etag": '"qa-etag"', "eligible_candidate": True}
            ],
        },
    }
    backed_up = cleanup.backup_objects(Storage(), "synthetic-bucket", report, tmp_path)
    assert calls == [{"Bucket": "synthetic-bucket", "Key": key, "IfMatch": '"qa-etag"'}]
    assert backed_up[0]["sha256"] == hashlib.sha256(content).hexdigest()
    assert (tmp_path / backed_up[0]["file"]).read_bytes() == content
    assert backed_up[0]["deleted"] is False


def test_foreign_media_is_rejected_before_request(tmp_path):
    report = {
        "scope_tenant_ids": [str(uuid4())],
        "storage": {
            "versioning": "Disabled",
            "multipart_uploads": [],
            "objects": [
                {
                    "key": f"LifeReel-Biography/tenants/{uuid4()}/foreign.txt",
                    "eligible_candidate": True,
                }
            ],
        },
    }
    with pytest.raises(RuntimeError, match="NONEXCLUSIVE_OBJECT_IN_SCOPE"):
        cleanup.backup_objects(None, "synthetic-bucket", report, tmp_path)

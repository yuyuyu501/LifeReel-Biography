"""Reset the explicitly authorized owner account after an external database backup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

import account_cleanup_audit as audit
from sqlalchemy import create_engine, delete, or_, select, update

BALANCES = (
    "paid_cents",
    "bonus_cents",
    "frozen_paid_cents",
    "frozen_bonus_cents",
    "token_remainder_nano",
)


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(".partial")
    temporary.write_text(
        json.dumps(value, default=str, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def target_predicate(table, tenants, account):
    if table.fullname in audit.USER_TABLES:
        return table.c.user_id == account
    return table.c.tenant_id.in_(tenants)


def preserved_hashes(connection, metadata, tenants, account):
    result = {}
    for name, table in sorted(metadata.tables.items()):
        query = select(table)
        if name in audit.BUSINESS_TABLES:
            query = query.where(or_(table.c.tenant_id.not_in(tenants), table.c.tenant_id.is_(None)))
        elif name in audit.USER_TABLES:
            query = query.where(or_(table.c.user_id != account, table.c.user_id.is_(None)))
        rows = [
            json.dumps(dict(row), default=str, sort_keys=True, ensure_ascii=True)
            for row in connection.execute(query).mappings()
        ]
        result[name] = hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()
    return result


def reset_database(connection, metadata, expected_account, expected_scope):
    """Caller owns the transaction; every failed invariant rolls the deletion back."""
    report = audit.audit_database(connection, metadata)
    if report["blockers"]:
        raise RuntimeError("DATABASE_PREFLIGHT_BLOCKED")
    if report["account"]["id"] != expected_account:
        raise RuntimeError("ACCOUNT_ID_CHANGED")
    if report["scope_tenant_ids"] != sorted(expected_scope):
        raise RuntimeError("OWNERSHIP_CHANGED")
    tenants = [UUID(value) for value in expected_scope]
    account = UUID(expected_account)
    before = preserved_hashes(connection, metadata, tenants, account)
    deleted = {}
    for name in audit.deletion_order(metadata):
        table = metadata.tables[name]
        deleted[name] = connection.execute(
            delete(table).where(target_predicate(table, tenants, account))
        ).rowcount
    wallets = metadata.tables["billing.wallets"]
    connection.execute(
        update(wallets)
        .where(wallets.c.tenant_id.in_(tenants))
        .values(**{field: 0 for field in BALANCES})
    )
    after = audit.audit_database(connection, metadata)
    if after["blockers"]:
        raise RuntimeError("DATABASE_POSTCHECK_BLOCKED")
    for name, info in after["tables"].items():
        if name != "billing.wallets" and name in audit.BUSINESS_TABLES | audit.USER_TABLES:
            if info["scope"]:
                raise RuntimeError("TARGET_BUSINESS_ROWS_REMAIN")
    if any(wallet[field] for wallet in after.get("wallets", []) for field in BALANCES):
        raise RuntimeError("WALLET_NOT_ZERO")
    if before != preserved_hashes(connection, metadata, tenants, account):
        raise RuntimeError("PRESERVED_ACCOUNT_OR_OTHER_TENANT_CHANGED")
    return {
        "deleted_rows": deleted,
        "target_business_rows_remaining": 0,
        "wallet_balances": "zero",
        "preserved_hashes": before,
        "account_and_other_tenants_verified": True,
    }


def s3_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL"),
        region_name=os.environ.get("S3_REGION_NAME", "us-east-1"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY"),
        config=Config(
            signature_version="s3v4",
            connect_timeout=10,
            read_timeout=60,
            s3={"addressing_style": os.environ.get("S3_ADDRESSING_STYLE", "path")},
        ),
    )


def backup_objects(client, bucket, report, directory):
    inventory = report["storage"]["objects"]
    if report["storage"]["versioning"] != "Disabled" or report["storage"]["multipart_uploads"]:
        raise RuntimeError("STORAGE_VERSION_OR_UPLOAD_REQUIRES_REVIEW")
    result = []
    for item in inventory:
        if item.get("exists") is False:
            continue
        key = item["key"]
        if not item["eligible_candidate"] or not audit.key_in_scope(
            key, report["scope_tenant_ids"]
        ):
            raise RuntimeError("NONEXCLUSIVE_OBJECT_IN_SCOPE")
        target = directory / (hashlib.sha256(key.encode()).hexdigest() + ".bin")
        response = client.get_object(Bucket=bucket, Key=key, IfMatch=item["etag"])
        body = response["Body"]
        try:
            with target.open("xb") as output:
                for block in iter(lambda stream=body: stream.read(1024 * 1024), b""):
                    output.write(block)
        finally:
            body.close()
        target.chmod(0o600)
        if target.stat().st_size != item["bytes"]:
            raise RuntimeError("OBJECT_BACKUP_SIZE_MISMATCH")
        result.append(
            {
                "key": key,
                "file": target.name,
                "bytes": item["bytes"],
                "sha256": file_hash(target),
                "etag": response["ETag"],
                "deleted": False,
            }
        )
    return result


def execute(expected_account, directory):
    database_dump = directory.parent / "database.dump"
    database_digest = directory.parent / "database.sha256"
    if not database_dump.is_file() or not database_digest.is_file():
        raise RuntimeError("EXTERNAL_DATABASE_BACKUP_REQUIRED")
    if file_hash(database_dump) != database_digest.read_text().strip():
        raise RuntimeError("EXTERNAL_DATABASE_BACKUP_HASH_MISMATCH")
    report = audit.run_audit(with_storage=True, with_cache=True)
    if not report["all_readonly_checks_passed"] or report["account"]["id"] != expected_account:
        raise RuntimeError("ACCOUNT_STORAGE_OR_CACHE_PREFLIGHT_BLOCKED")
    directory.mkdir(mode=0o700)
    write_json(directory / "preflight.json", report)
    objects_dir = directory / "objects"
    objects_dir.mkdir(mode=0o700)
    client = s3_client()
    bucket = os.environ["S3_BUCKET"]
    engine = create_engine(os.environ["DATABASE_URL"], echo=False)
    result = {
        "account": audit.TARGET_EMAIL,
        "account_id": expected_account,
        "tenant_ids": report["scope_tenant_ids"],
        "phase": "backing_up",
    }
    try:
        objects = backup_objects(client, bucket, report, objects_dir)
        local_files = report["cache"]["tenant_local_files"]
        if local_files:
            raise RuntimeError("LOCAL_FILES_REQUIRE_BACKUP_BEFORE_RESET")
        result.update(objects=objects, media_backup_bytes=sum(item["bytes"] for item in objects))
        write_json(directory / "results.json", result)
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '60s'")
            metadata = audit.reflect_database(connection)
            preparer = connection.dialect.identifier_preparer
            names = ", ".join(preparer.format_table(table) for table in metadata.tables.values())
            connection.exec_driver_sql("LOCK TABLE " + names + " IN ACCESS EXCLUSIVE MODE")
            fresh = audit.audit_database(connection, metadata)
            if fresh["blockers"] or fresh["objects"] != report["objects"]:
                raise RuntimeError("DATABASE_REFERENCES_CHANGED_DURING_BACKUP")
            result["database"] = reset_database(
                connection, metadata, expected_account, report["scope_tenant_ids"]
            )
        result["phase"] = "database_reset"
        write_json(directory / "results.json", result)
        for item in objects:
            source = objects_dir / item["file"]
            if file_hash(source) != item["sha256"]:
                raise RuntimeError("MEDIA_BACKUP_HASH_CHANGED")
            current = client.head_object(Bucket=bucket, Key=item["key"])
            if current["ETag"] != item["etag"] or current["ContentLength"] != item["bytes"]:
                raise RuntimeError("MEDIA_SOURCE_CHANGED")
            client.delete_object(Bucket=bucket, Key=item["key"])
            item["deleted"] = True
            write_json(directory / "results.json", result)
        import redis

        cache = redis.from_url(os.environ["REDIS_URL"], socket_timeout=10)
        try:
            for item in report["cache"]["voice_revision_keys"]:
                key = item["key"]
                if not any(
                    key.startswith(f"lifereel:voice-revision:{tenant}:")
                    for tenant in report["scope_tenant_ids"]
                ):
                    raise RuntimeError("CACHE_KEY_OUTSIDE_SCOPE")
                cache.delete(key)
        finally:
            cache.close()
        after = audit.run_audit(with_storage=True, with_cache=True)
        if not after["all_readonly_checks_passed"] or after["storage"]["objects"]:
            raise RuntimeError("FINAL_STORAGE_OR_DATABASE_CHECK_FAILED")
        if after["cache"]["voice_revision_keys"] or after["cache"]["target_queue_items"]:
            raise RuntimeError("TARGET_CACHE_REMAINS")
        write_json(directory / "after.json", after)
        result.update(
            phase="complete",
            media_objects_deleted=len(objects),
            cache_verified=True,
            storage_verified=True,
        )
        write_json(directory / "results.json", result)
        return {
            key: result[key]
            for key in (
                "account",
                "phase",
                "media_objects_deleted",
                "media_backup_bytes",
                "cache_verified",
                "storage_verified",
            )
        } | {
            "database": {
                key: result["database"][key]
                for key in (
                    "deleted_rows",
                    "target_business_rows_remaining",
                    "wallet_balances",
                    "account_and_other_tenants_verified",
                )
            }
        }
    finally:
        engine.dispose()
        client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--backup-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        expected = str(UUID(args.expected_account_id))
        result = execute(expected, args.backup_dir)
    except Exception as exc:
        # Database and provider exceptions may contain credentials or private record values.
        message = str(exc) if type(exc) is RuntimeError else "CLEANUP_FAILED_DETAILS_REDACTED"
        print(json.dumps({"phase": "failed", "error_type": type(exc).__name__, "error": message}))
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

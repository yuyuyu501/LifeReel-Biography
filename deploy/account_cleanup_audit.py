"""Read-only cleanup preflight. This tool has no apply or deletion mode."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import UUID

from sqlalchemy import JSON, MetaData, Uuid, and_, create_engine, func, inspect, select

TARGET_EMAIL = "owner@lifereel.local"
SCHEMA_TABLES = {
    "identity": "account_audits account_phones audit_events auth_rate_limits consent_grants "
    "mini_sessions persons platform_identities sms_challenges tenant_memberships tenants "
    "user_accounts",
    "interview": "chapters interview_rounds interview_sessions interview_turn_workflows "
    "interview_voice_calls life_profiles life_profile_entries life_profile_revisions",
    "memory": "memory_claims memory_conflicts memory_entities timeline_anchors",
    "script": "script_generation_receipts script_projects script_scenes script_shots",
    "book": "books book_chapters book_revisions",
    "media": "chapter_reference_packages evidence_observations evidence_uploads generated_assets "
    "production_runs publications restoration_photos source_assets transcript_segments "
    "transcript_versions transcripts",
    "billing": "billing_charges billing_commands provider_usage recharge_orders "
    "wallet_ledger wallets",
    "tasks": "job_deliveries jobs outbox_events",
    "model_gateway": "model_invocations",
}
EXPECTED_TABLES = {
    f"{schema}.{name}" for schema, names in SCHEMA_TABLES.items() for name in names.split()
}
PRESERVE = {
    "identity.user_accounts",
    "identity.account_phones",
    "identity.platform_identities",
    "identity.mini_sessions",
    "identity.tenant_memberships",
    "identity.tenants",
    "identity.sms_challenges",
    "identity.auth_rate_limits",
    "public.alembic_version",
}
USER_TABLES = {"identity.account_audits"}
BUSINESS_TABLES = EXPECTED_TABLES - PRESERVE - USER_TABLES
TERMINAL = {"completed", "failed", "cancelled"}
ACTIVE_CHECKS = {
    "tasks.jobs": ("status", TERMINAL),
    "tasks.outbox_events": ("status", {"published"}),
    "media.production_runs": ("status", TERMINAL),
    "interview.interview_turn_workflows": ("status", TERMINAL),
    "interview.interview_voice_calls": ("status", {"completed", "failed", "ended", "closed"}),
    "model_gateway.model_invocations": ("state", {"completed", "failed"}),
    "script.script_generation_receipts": ("status", TERMINAL),
    "billing.billing_charges": ("status", {"settled", "released"}),
    "billing.recharge_orders": ("status", {"credited", "rejected", "cancelled"}),
}
PROJECT_PREFIX = "LifeReel-Biography/"


def fingerprint(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def uuid_text(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def tenant_prefixes(tenant):
    return [
        f"{PROJECT_PREFIX}{part}/{tenant}/"
        for part in (
            "tenants",
            "generated",
            "restoration",
            "diagnostics",
            "uploads/staging",
            "evidence",
        )
    ] + [f"{tenant}/interview-voice/"]


def audit_prefixes(tenant):
    return tenant_prefixes(tenant)


def key_in_scope(key, tenants):
    if not isinstance(key, str) or not key or "\\" in key or "\x00" in key:
        return False
    if any(part in {"", ".", ".."} for part in key.split("/")):
        return False
    decoded = unquote(key)
    if decoded != key and ("\\" in decoded or any(p in {".", ".."} for p in decoded.split("/"))):
        return False
    return any(
        key.startswith(prefix) and len(key) > len(prefix)
        for tenant in tenants
        for prefix in tenant_prefixes(tenant)
    )


def json_references(value, field=""):
    """Inspect values in memory; emit only object keys and UUID references."""
    keys, ids = set(), set()
    if isinstance(value, dict):
        for name, child in value.items():
            child_keys, child_ids = json_references(child, str(name))
            keys.update(child_keys)
            ids.update(child_ids)
    elif isinstance(value, list):
        for child in value:
            child_keys, child_ids = json_references(child, field)
            keys.update(child_keys)
            ids.update(child_ids)
    elif isinstance(value, str):
        identifier = uuid_text(value)
        if identifier:
            ids.add(identifier)
        if value.startswith(PROJECT_PREFIX):
            keys.add(value)
        elif value.startswith(("https://", "http://", "s3://")):
            path = unquote(urlsplit(value).path).lstrip("/")
            if path.startswith(PROJECT_PREFIX):
                keys.add(path)
            elif len(path.split("/")) >= 3:
                parts = path.split("/")
                if uuid_text(parts[0]) and parts[1] == "interview-voice":
                    keys.add(path)
        elif len(value.split("/")) >= 3:
            parts = value.split("/")
            if uuid_text(parts[0]) and parts[1] == "interview-voice":
                keys.add(value)
            elif field in {"storage_key", "object_key", "keys"}:
                keys.add(value)
        elif field in {"storage_key", "object_key", "keys"} and value:
            keys.add(value)
    return keys, ids


def deletion_order(metadata):
    remaining = set((BUSINESS_TABLES | USER_TABLES) & metadata.tables.keys()) - {"billing.wallets"}
    result = []
    while remaining:
        parents = {
            element.column.table.fullname
            for name in remaining
            for constraint in metadata.tables[name].foreign_key_constraints
            for element in constraint.elements
            if element.column.table.fullname != name
        }
        leaves = sorted(remaining - parents)
        if not leaves:
            raise ValueError("BUSINESS_FOREIGN_KEY_CYCLE")
        result.extend(leaves)
        remaining.difference_update(leaves)
    return result


def reflect_database(connection):
    metadata = MetaData()
    inspector = inspect(connection)
    for schema in inspector.get_schema_names():
        if schema == "information_schema" or schema.startswith("pg_"):
            continue
        metadata.reflect(bind=connection, schema=schema)
    return metadata


def row_token(table, row):
    return fingerprint("|".join(str(row.get(column.name, "")) for column in table.primary_key))


def read_projection(connection, table):
    columns = set(table.primary_key.columns)
    columns.update(
        element.parent
        for constraint in table.foreign_key_constraints
        for element in constraint.elements
    )
    safe_names = {
        "tenant_id",
        "user_id",
        "status",
        "state",
        "storage_key",
        "paid_cents",
        "bonus_cents",
        "frozen_paid_cents",
        "frozen_bonus_cents",
        "token_remainder_nano",
        "lease_expires_at",
        "ended_at",
        "expires_at",
    }
    columns.update(
        column
        for column in table.columns
        if column.name in safe_names or isinstance(column.type, (JSON, Uuid))
    )
    return list(connection.execute(select(*sorted(columns, key=lambda c: c.name))).mappings())


def audit_database(connection, metadata):
    blockers = []
    report = {
        "mode": "read_only",
        "execution_supported": False,
        "email": TARGET_EMAIL,
        "observed_at": datetime.now(UTC).isoformat(),
        "blockers": blockers,
        "preserved_tables": sorted(PRESERVE),
        "tables": {},
        "foreign_keys": [],
    }
    present = set(metadata.tables)
    missing = sorted(EXPECTED_TABLES - present)
    unknown = sorted(present - EXPECTED_TABLES - {"public.alembic_version"})
    if missing or unknown:
        blockers.append({"code": "UNREVIEWED_SCHEMA", "missing": missing, "unknown": unknown})
    required = {"identity.user_accounts", "identity.tenant_memberships", "identity.tenants"}
    if not required <= present:
        raise ValueError("IDENTITY_SCHEMA_UNAVAILABLE")
    users = metadata.tables["identity.user_accounts"]
    accounts = list(
        connection.execute(
            select(users.c.id, users.c.email, users.c.is_active, users.c.deleted_at).where(
                users.c.email == TARGET_EMAIL
            )
        ).mappings()
    )
    if len(accounts) != 1:
        raise ValueError("TARGET_ACCOUNT_NOT_UNIQUE")
    account = accounts[0]
    account_id = account["id"]
    report["account"] = {
        "id": str(account_id),
        "email": TARGET_EMAIL,
        "is_active": account["is_active"],
        "has_deleted_at": account["deleted_at"] is not None,
    }
    if not account["is_active"] or account["deleted_at"] is not None:
        blockers.append({"code": "TARGET_LOGIN_INACTIVE"})
    memberships = metadata.tables["identity.tenant_memberships"]
    member_rows = list(
        connection.execute(
            select(memberships.c.tenant_id, memberships.c.user_id, memberships.c.role)
        ).mappings()
    )
    linked = {row["tenant_id"] for row in member_rows if row["user_id"] == account_id}
    tenants, ownership = set(), []
    platforms = metadata.tables.get("identity.platform_identities")
    platform_rows = (
        []
        if platforms is None
        else list(connection.execute(select(platforms.c.tenant_id, platforms.c.user_id)).mappings())
    )
    for tenant in sorted(linked, key=str):
        members = [row for row in member_rows if row["tenant_id"] == tenant]
        exclusive = (
            len(members) == 1
            and members[0]["user_id"] == account_id
            and members[0]["role"] == "owner"
        )
        foreign_identities = sum(
            row["tenant_id"] == tenant and row["user_id"] != account_id for row in platform_rows
        )
        exclusive = exclusive and foreign_identities == 0
        ownership.append(
            {
                "tenant_id": str(tenant),
                "exclusive_owner": exclusive,
                "members": [
                    {"user_id": str(row["user_id"]), "role": row["role"]} for row in members
                ],
                "other_platform_identity_count": foreign_identities,
            }
        )
        if exclusive:
            tenants.add(tenant)
        else:
            blockers.append({"code": "SHARED_OR_NONOWNER_TENANT", "tenant_id": str(tenant)})
    if not tenants:
        blockers.append({"code": "NO_EXCLUSIVE_TENANT"})
    if any(
        row["user_id"] == account_id and row["tenant_id"] not in linked for row in platform_rows
    ):
        blockers.append({"code": "LOGIN_IDENTITY_WITHOUT_MEMBERSHIP"})
    report["ownership"] = ownership
    report["scope_tenant_ids"] = sorted(map(str, tenants))
    rows_by_table, selected = {}, {}
    for name, table in sorted(metadata.tables.items()):
        total = connection.scalar(select(func.count()).select_from(table))
        if name in PRESERVE:
            report["tables"][name] = {"total": total, "scope": 0, "action": "preserve"}
            continue
        rows = read_projection(connection, table)
        rows_by_table[name] = rows
        target = [
            row
            for row in rows
            if (name in BUSINESS_TABLES and row.get("tenant_id") in tenants)
            or (name in USER_TABLES and row.get("user_id") == account_id)
        ]
        selected[name] = {row_token(table, row) for row in target}
        report["tables"][name] = {
            "total": total,
            "scope": len(target),
            "scope_digest": fingerprint("|".join(sorted(selected[name]))),
            "action": "zero_existing_wallet"
            if name == "billing.wallets"
            else "delete_target_user_rows"
            if name in USER_TABLES
            else "delete_tenant_rows"
            if name in BUSINESS_TABLES
            else "unreviewed",
            "scope_column": "user_id" if name in USER_TABLES else "tenant_id",
            "by_linked_tenant": {
                str(tenant): sum(row.get("tenant_id") == tenant for row in rows)
                for tenant in sorted(linked, key=str)
            },
        }
        if name in BUSINESS_TABLES and "tenant_id" not in table.c:
            blockers.append({"code": "BUSINESS_TABLE_WITHOUT_TENANT", "table": name})
        if name in ACTIVE_CHECKS:
            column, safe_states = ACTIVE_CHECKS[name]
            states = Counter(str(row.get(column)) for row in target)
            report["tables"][name]["states"] = dict(sorted(states.items()))
            for row in target:
                active = row.get(column) not in safe_states
                if name == "tasks.jobs" and row.get("lease_expires_at"):
                    lease = row["lease_expires_at"]
                    if isinstance(lease, datetime):
                        active |= lease.replace(tzinfo=lease.tzinfo or UTC) > datetime.now(UTC)
                if name == "interview.interview_voice_calls":
                    active |= row.get("ended_at") is None
                if active:
                    blockers.append(
                        {
                            "code": "ACTIVE_OR_UNSETTLED_ROW",
                            "table": name,
                            "row": row_token(table, row),
                            "state": str(row.get(column)),
                        }
                    )
        if name == "billing.wallets":
            report["wallets"] = [
                {
                    "tenant_id": str(row["tenant_id"]),
                    **{
                        field: row.get(field)
                        for field in (
                            "paid_cents",
                            "bonus_cents",
                            "frozen_paid_cents",
                            "frozen_bonus_cents",
                            "token_remainder_nano",
                        )
                    },
                }
                for row in target
            ]
            if any(row.get("frozen_paid_cents") or row.get("frozen_bonus_cents") for row in target):
                blockers.append({"code": "FROZEN_WALLET"})
    # Check every incoming constraint, including SET NULL and CASCADE from other schemas.
    for child in metadata.tables.values():
        for constraint in child.foreign_key_constraints:
            elements = list(constraint.elements)
            parent = elements[0].column.table
            report["foreign_keys"].append(
                {
                    "child": child.fullname,
                    "columns": [e.parent.name for e in elements],
                    "parent": parent.fullname,
                    "parent_columns": [e.column.name for e in elements],
                    "ondelete": constraint.ondelete or "NO ACTION",
                }
            )
            if parent.fullname not in BUSINESS_TABLES or parent.fullname == "billing.wallets":
                continue
            parent_alias = parent.alias()
            target_predicate = parent_alias.c.tenant_id.in_(tenants)
            join = and_(*(e.parent == parent_alias.c[e.column.name] for e in elements))
            child_columns = list(child.primary_key.columns)
            if "tenant_id" in child.c and child.c.tenant_id not in child_columns:
                child_columns.append(child.c.tenant_id)
            hits = connection.execute(
                select(*child_columns)
                .select_from(child.join(parent_alias, join))
                .where(target_predicate)
            ).mappings()
            for row in hits:
                if row_token(child, row) not in selected.get(child.fullname, set()):
                    blockers.append(
                        {
                            "code": "EXTERNAL_FOREIGN_KEY_REFERENCE",
                            "child": child.fullname,
                            "parent": parent.fullname,
                            "ondelete": constraint.ondelete or "NO ACTION",
                            "row": row_token(child, row),
                        }
                    )
    target_ids = {
        uuid_text(row[column.name])
        for name, rows in rows_by_table.items()
        for row in rows
        if row_token(metadata.tables[name], row) in selected[name]
        for column in metadata.tables[name].primary_key
        if column.name != "tenant_id" and uuid_text(row[column.name])
    }
    object_refs = defaultdict(list)
    for name, rows in rows_by_table.items():
        table = metadata.tables[name]
        for row in rows:
            token = row_token(table, row)
            in_scope = token in selected[name]
            keys, ids = set(), set()
            for column in table.columns:
                if isinstance(column.type, JSON):
                    child_keys, child_ids = json_references(row.get(column.name))
                    keys.update(child_keys)
                    ids.update(child_ids)
                elif column.name != "tenant_id" and isinstance(column.type, Uuid):
                    identifier = uuid_text(row.get(column.name))
                    if identifier:
                        ids.add(identifier)
            if row.get("storage_key"):
                keys.add(row["storage_key"])
            if not in_scope and ids & target_ids:
                blockers.append(
                    {
                        "code": "EXTERNAL_JSON_REFERENCE",
                        "table": name,
                        "row": token,
                        "reference_count": len(ids & target_ids),
                    }
                )
            for key in keys:
                object_refs[key].append({"table": name, "row": token, "in_scope": in_scope})
    scope_strings = set(report["scope_tenant_ids"])
    objects = []
    for key, refs in sorted(object_refs.items()):
        has_target_reference = any(ref["in_scope"] for ref in refs)
        under_scope = key_in_scope(key, scope_strings)
        if not has_target_reference and not under_scope:
            continue
        shared = any(not ref["in_scope"] for ref in refs)
        eligible = has_target_reference and under_scope and not shared
        objects.append(
            {
                "key": key,
                "key_sha256": fingerprint(key),
                "references": refs,
                "eligible_candidate": eligible,
                "shared": shared,
            }
        )
        if shared or not under_scope:
            blockers.append({"code": "SHARED_OR_UNSAFE_OBJECT", "key_sha256": fingerprint(key)})
    report["objects"] = objects
    report["review_delete_order"] = deletion_order(metadata)
    report["wallet_action"] = "keep existing wallet; zero all five balance/remainder fields"
    report["login_action"] = "preserve account, password, identity, sessions and memberships"
    report["account_audits_action"] = "delete only target user_id rows; never select by actor_id"
    report["database_preflight_passed"] = not blockers
    return report


def audit_storage(report, client, bucket):
    """Only LIST/HEAD requests; exact exclusive prefixes also own unreferenced objects."""
    scope = report["scope_tenant_ids"]
    known = {item["key"]: item for item in report["objects"]}
    inventory = {}
    for tenant in scope:
        for prefix in audit_prefixes(tenant):
            for page in client.get_paginator("list_objects_v2").paginate(
                Bucket=bucket, Prefix=prefix
            ):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    inventory[key] = {
                        "key": key,
                        "bytes": obj["Size"],
                        "etag": obj.get("ETag"),
                        "last_modified": str(obj.get("LastModified")),
                        "unreferenced": key not in known,
                        "eligible_candidate": (key not in known or known[key]["eligible_candidate"])
                        and key_in_scope(key, scope),
                    }
    for key, entry in known.items():
        if key not in inventory:
            try:
                obj = client.head_object(Bucket=bucket, Key=key)
                inventory[key] = {
                    "key": key,
                    "bytes": obj["ContentLength"],
                    "etag": obj.get("ETag"),
                    "exists": True,
                    "eligible_candidate": entry["eligible_candidate"],
                }
            except Exception as exc:
                response = getattr(exc, "response", {})
                code = str(response.get("Error", {}).get("Code", ""))
                if code in {"404", "NoSuchKey", "NotFound"}:
                    inventory[key] = {"key": key, "exists": False, "eligible_candidate": False}
                else:
                    raise RuntimeError("OBJECT_HEAD_FAILED") from None
    versioning = client.get_bucket_versioning(Bucket=bucket).get("Status", "Disabled")
    versions, multiparts = [], []
    for tenant in scope:
        for prefix in audit_prefixes(tenant):
            if versioning in {"Enabled", "Suspended"}:
                for page in client.get_paginator("list_object_versions").paginate(
                    Bucket=bucket, Prefix=prefix
                ):
                    for obj in page.get("Versions", []) + page.get("DeleteMarkers", []):
                        versions.append(
                            {
                                "key": obj["Key"],
                                "version_id": obj["VersionId"],
                                "is_latest": obj.get("IsLatest"),
                                "review_only": True,
                            }
                        )
            for page in client.get_paginator("list_multipart_uploads").paginate(
                Bucket=bucket, Prefix=prefix
            ):
                for obj in page.get("Uploads", []):
                    multiparts.append(
                        {
                            "key": obj["Key"],
                            "upload_id": obj["UploadId"],
                            "initiated": str(obj.get("Initiated")),
                            "review_only": True,
                        }
                    )
    report["storage"] = {
        "verified": True,
        "backend": "s3",
        "versioning": versioning,
        "objects": sorted(inventory.values(), key=lambda item: item["key"]),
        "versions": versions,
        "multipart_uploads": multiparts,
        "unreferenced_action": "backup/hash then delete exclusive prefixes without foreign refs",
    }
    if multiparts:
        report["blockers"].append(
            {"code": "MULTIPART_UPLOADS_REQUIRE_REVIEW", "count": len(multiparts)}
        )


def audit_cache(report, client, root, queue):
    scope = report["scope_tenant_ids"]
    revisions = []
    for tenant in scope:
        for key in client.scan_iter(match=f"lifereel:voice-revision:{tenant}:*", count=100):
            revisions.append(
                {"key": key.decode() if isinstance(key, bytes) else key, "ttl": client.ttl(key)}
            )
    queued = []
    queue_length = client.llen(queue)
    for offset in range(0, queue_length, 100):
        for raw in client.lrange(queue, offset, offset + 99):
            try:
                item = json.loads(raw)
            except (ValueError, TypeError):
                report["blockers"].append({"code": "UNPARSEABLE_SHARED_QUEUE_ITEM"})
                continue
            if isinstance(item, dict) and str(item.get("tenant_id")) in scope:
                queued.append(
                    {"job_id": str(item.get("job_id")), "tenant_id": str(item["tenant_id"])}
                )
    if queued:
        report["blockers"].append({"code": "TARGET_ITEMS_IN_SHARED_QUEUE", "count": len(queued)})
    root = Path(root)
    files, held = [], 0
    if root.is_dir():
        resolved = root.resolve()
        for tenant in scope:
            for prefix in audit_prefixes(tenant):
                directory = root / prefix
                ancestors = [
                    root.joinpath(*directory.relative_to(root).parts[:index])
                    for index in range(1, len(directory.relative_to(root).parts) + 1)
                ]
                if any(
                    path.is_symlink() for path in ancestors
                ) or not directory.resolve().is_relative_to(resolved):
                    held += 1
                    continue
                if directory.is_dir():
                    for current, directories, names in os.walk(directory, followlinks=False):
                        # Never traverse a symlink into another tenant or a shared mount.
                        kept = []
                        for name in directories:
                            child = Path(current) / name
                            if child.is_symlink():
                                held += 1
                            else:
                                kept.append(name)
                        directories[:] = kept
                        for name in names:
                            child = Path(current) / name
                            if child.is_symlink() or not child.resolve().is_relative_to(resolved):
                                held += 1
                                continue
                            files.append(
                                {
                                    "relative_key": child.relative_to(root).as_posix(),
                                    "bytes": child.stat().st_size,
                                    "review_only": True,
                                }
                            )
    report["cache"] = {
        "verified": True,
        "voice_revision_keys": revisions,
        "shared_queue_length": queue_length,
        "target_queue_items": queued,
        "tenant_local_files": files,
        "held_paths": held,
        "unattributed_tmp_action": "retain; cannot prove ownership",
        "browser_cache_action": "clear only target session in its browser",
        "shared_models_payment_assets_logs_action": "preserve",
    }
    if held:
        report["blockers"].append({"code": "LOCAL_PATH_REQUIRES_REVIEW", "count": held})


def run_audit(with_storage=False, with_cache=False):
    engine = create_engine(os.environ["DATABASE_URL"], echo=False)
    try:
        with engine.connect() as connection:
            with connection.begin():
                if connection.dialect.name != "postgresql":
                    raise ValueError("PRODUCTION_AUDIT_REQUIRES_POSTGRESQL")
                connection.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                connection.exec_driver_sql("SET LOCAL statement_timeout = '30s'")
                connection.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
                metadata = reflect_database(connection)
                report = audit_database(connection, metadata)
                version = metadata.tables.get("public.alembic_version")
                report["migration"] = (
                    []
                    if version is None
                    else list(connection.scalars(select(version.c.version_num)))
                )
        # External snapshots are read-only but not atomic with the database snapshot.
        report["storage"] = {"verified": False}
        report["cache"] = {"verified": False}
        if with_storage:
            if os.environ.get("STORAGE_BACKEND", "local") != "s3":
                report["blockers"].append({"code": "STORAGE_BACKEND_NOT_AUDITED"})
            else:
                import boto3
                from botocore.config import Config

                client = boto3.client(
                    "s3",
                    endpoint_url=os.environ.get("S3_ENDPOINT_URL"),
                    region_name=os.environ.get("S3_REGION_NAME", "us-east-1"),
                    aws_access_key_id=os.environ.get("S3_ACCESS_KEY"),
                    aws_secret_access_key=os.environ.get("S3_SECRET_KEY"),
                    config=Config(
                        signature_version="s3v4",
                        connect_timeout=10,
                        read_timeout=30,
                        s3={"addressing_style": os.environ.get("S3_ADDRESSING_STYLE", "path")},
                    ),
                )
                try:
                    audit_storage(report, client, os.environ["S3_BUCKET"])
                except Exception as exc:
                    report["blockers"].append(
                        {"code": "STORAGE_AUDIT_INCOMPLETE", "error_type": type(exc).__name__}
                    )
                finally:
                    client.close()
        if with_cache:
            import redis

            client = redis.from_url(os.environ["REDIS_URL"], socket_timeout=10)
            try:
                audit_cache(
                    report,
                    client,
                    os.environ.get("LOCAL_STORAGE_PATH", "/data/private"),
                    os.environ.get("WORKER_QUEUE", "lifereel:jobs"),
                )
            except Exception as exc:
                report["blockers"].append(
                    {"code": "CACHE_AUDIT_INCOMPLETE", "error_type": type(exc).__name__}
                )
            finally:
                client.close()
        report["all_readonly_checks_passed"] = (
            not report["blockers"] and report["storage"]["verified"] and report["cache"]["verified"]
        )
        report["future_execution_requires"] = [
            "this read_only tool has no execution mode",
            "quiesce all writers, live voice sockets, workers, outbox and upload clients",
            "fresh database/environment backup, exact object backup and previous runtime images",
            "repeat ownership, references and activity checks under write fencing",
            "single database transaction; keep authentication and zero existing wallets",
            "delete verified exact object keys after DB success; retain shared keys",
            "verify login identity/password, other tenants, zero business rows and caches",
        ]
        return report
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-storage", action="store_true")
    parser.add_argument("--with-cache", action="store_true")
    args = parser.parse_args()
    try:
        report = run_audit(args.with_storage, args.with_cache)
    except Exception as exc:
        # Driver exceptions can contain connection URLs, credentials or row contents.
        print(
            json.dumps(
                {
                    "mode": "read_only",
                    "error_type": type(exc).__name__,
                    "error": "AUDIT_FAILED_DETAILS_REDACTED",
                }
            )
        )
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

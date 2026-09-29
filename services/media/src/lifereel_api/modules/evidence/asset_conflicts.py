"""Recognize only the uniqueness races that can resolve to an existing asset."""

import sqlite3

from sqlalchemy.exc import IntegrityError


def is_asset_duplicate(error: IntegrityError) -> bool:
    original = error.orig
    if getattr(original, "sqlstate", None) == "23505":
        return getattr(getattr(original, "diag", None), "constraint_name", None) in {
            "uq_asset_tenant_subject_sha256",
            "uq_source_assets_storage_key",
        }
    # SQLite reports columns instead of constraint names. Do not mistake a foreign
    # key, NOT NULL, primary key, or unrelated unique violation for idempotency.
    return (
        isinstance(original, sqlite3.IntegrityError)
        and getattr(original, "sqlite_errorcode", None) == sqlite3.SQLITE_CONSTRAINT_UNIQUE
        and str(original) in {
            "UNIQUE constraint failed: source_assets.storage_key",
            "UNIQUE constraint failed: source_assets.tenant_id, "
            "source_assets.subject_id, source_assets.sha256",
        }
    )

from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.dialects import postgresql

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing import router, service
from lifereel_api.modules.billing.models import LedgerEntry, Wallet
from lifereel_api.modules.identity.models import Tenant


@contextmanager
def observed_session(db):
    sql, commits = [], []

    def execute(state):
        sql.append(str(state.statement.compile(dialect=postgresql.dialect())))

    def committed(session):
        commits.append(True)

    def writes(conn, cursor, statement, parameters, context, executemany):
        if not statement.lstrip().upper().startswith("SELECT"):
            sql.append(statement)

    event.listen(db, "do_orm_execute", execute)
    event.listen(db, "after_commit", committed)
    event.listen(db.get_bind(), "before_cursor_execute", writes)
    try:
        yield sql, commits
    finally:
        event.remove(db, "do_orm_execute", execute)
        event.remove(db, "after_commit", committed)
        event.remove(db.get_bind(), "before_cursor_execute", writes)


def new_tenant():
    tenant_id = uuid4()
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="Wallet reads", slug=str(tenant_id)))
        db.commit()
    return tenant_id


def test_existing_wallet_read_has_one_select_no_locks_writes_or_commit():
    tenant_id = new_tenant()
    with SessionLocal() as db:
        row = service.lock_wallet(db, tenant_id)
        row.paid_cents = -120
        row.bonus_cents = 100
        row.frozen_paid_cents = 30
        row.frozen_bonus_cents = 40
        row.token_remainder_nano = 123456
        db.commit()
        db.refresh(row)
        before = row.updated_at
        with observed_session(db) as (sql, commits):
            payload = router.wallet(db, tenant_id)
        assert payload == {
            "paid_cents": -120, "bonus_cents": 100, "frozen_cents": 70,
            "available_cents": -90, "debt_cents": 20, "token_remainder_nano": 123456,
            "prices": service.prices(),
            "recharge": {"mode": "disabled", "min_cents": 1, "max_cents": 20000},
        }
        assert row.updated_at == before
        assert not db.new and not db.dirty and not db.deleted
        assert all("FOR " not in statement for statement in sql), sql
        assert len(sql) == 1, sql
        assert commits == []


def test_first_read_persists_one_welcome_grant():
    tenant_id = new_tenant()
    with SessionLocal() as db, observed_session(db) as (sql, commits):
        first = router.wallet(db, tenant_id)
        assert first["available_cents"] == get_settings().billing_welcome_bonus_cents
        assert sum("FOR NO KEY UPDATE" in statement for statement in sql) == 2
        assert len(commits) == 1
    for _ in range(3):
        with SessionLocal() as db:
            assert router.wallet(db, tenant_id) == first
    with SessionLocal() as db:
        entries = list(db.scalars(select(LedgerEntry).where(LedgerEntry.tenant_id == tenant_id)))
        assert len(entries) == 1
        assert entries[0].event_key == "welcome:v1"
        assert entries[0].amount_cents == first["available_cents"]


def test_read_refreshes_cached_balance_after_settlement():
    tenant_id = new_tenant()
    with SessionLocal() as reader:
        router.wallet(reader, tenant_id)
        cached = reader.get(Wallet, tenant_id)
        reader.rollback()
        # Keep a loaded identity-map object across another transaction's settlement.
        assert cached.bonus_cents == get_settings().billing_welcome_bonus_cents
        with SessionLocal() as writer:
            service.reserve(writer, tenant_id, "read-consistency", 150, "video", "Test", {})
            writer.commit()
        frozen = router.wallet(reader, tenant_id)
        assert frozen["frozen_cents"] == 150
        assert frozen["available_cents"] == frozen["bonus_cents"] - 150
        with SessionLocal() as writer:
            service.transition(writer, tenant_id, "read-consistency", True)
            writer.commit()
        settled = router.wallet(reader, tenant_id)
        assert settled["frozen_cents"] == 0
        assert settled["available_cents"] == frozen["available_cents"]
        assert settled["bonus_cents"] == frozen["bonus_cents"] - 150
        assert reader.scalar(select(func.count()).select_from(LedgerEntry).where(
            LedgerEntry.tenant_id == tenant_id, LedgerEntry.event == "consume",
        )) == 1


def test_unknown_tenant_does_not_receive_wallet():
    tenant_id = uuid4()
    with SessionLocal() as db:
        with pytest.raises(ApiError) as exc:
            router.wallet(db, tenant_id)
        assert exc.value.code == ErrorCode.WALLET_NOT_FOUND
        assert db.get(Wallet, tenant_id) is None


def test_first_read_rechecks_wallet_created_between_probe_and_lock(monkeypatch):
    tenant_id = new_tenant()
    lock_wallet = service.lock_wallet

    def competing_initializer(db, requested_tenant):
        # Deterministically interleave another committed billing transaction after
        # the missing-wallet probe, before the reader acquires its initialization lock.
        with SessionLocal() as writer:
            service.reserve(writer, requested_tenant, "competing", 75, "video", "Test", {})
            writer.commit()
        return lock_wallet(db, requested_tenant)

    def initialize_once(db, requested_tenant):
        monkeypatch.setattr(service, "lock_wallet", lock_wallet)
        return competing_initializer(db, requested_tenant)

    monkeypatch.setattr(service, "lock_wallet", initialize_once)
    with SessionLocal() as db:
        payload = router.wallet(db, tenant_id)
        assert payload["bonus_cents"] == get_settings().billing_welcome_bonus_cents
        assert payload["frozen_cents"] == 75
        assert payload["available_cents"] == payload["bonus_cents"] - 75
        assert db.scalar(select(func.count()).select_from(LedgerEntry).where(
            LedgerEntry.tenant_id == tenant_id, LedgerEntry.event_key == "welcome:v1",
        )) == 1

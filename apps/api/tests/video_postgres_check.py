"""Opt-in migration and concurrency checks against a disposable local database."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from alembic.config import Config

from alembic import command

os.environ.update({
    "APP_ENV": "test", "AUTO_CREATE_SCHEMA": "false",
    "DATABASE_URL": "postgresql+psycopg://postgres:lifereel-disposable-test@"
                    "127.0.0.1:55440/lifereel_video_check",
    "PGOPTIONS": "-c statement_timeout=15000 -c lock_timeout=10000",
})

from lifereel_api.core.database import SessionLocal  # noqa: E402
from lifereel_api.core.errors import ApiError  # noqa: E402
from lifereel_api.main import app  # noqa: E402,F401
from lifereel_api.modules.billing import service  # noqa: E402
from lifereel_api.modules.identity.models import Tenant  # noqa: E402


def main():
    config = Config("alembic.ini")
    command.upgrade(config, "20260911_0022")
    tenant_id = uuid4()
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="Disposable video test", slug=str(tenant_id)))
        db.commit()
        wallet = service.lock_wallet(db, tenant_id)
        wallet.bonus_cents = 2000
        db.commit()
    command.upgrade(config, "head")

    def reserve(index):
        with SessionLocal() as db:
            try:
                service.reserve(db, tenant_id, f"parallel-{index}", 2400, "video_hold",
                                "test", {}, allow_overdraft=True)
                db.commit()
                return index
            except ApiError as exc:
                assert exc.code.value == "WALLET_INSUFFICIENT_BALANCE"
                return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(8)))
    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    with SessionLocal() as db:
        wallet = service.lock_wallet(db, tenant_id)
        assert service.available(wallet) == -400
        assert wallet.frozen_bonus_cents + wallet.frozen_paid_cents == 2400
        db.commit()

    def settle(_):
        with SessionLocal() as db:
            service.transition(db, tenant_id, f"parallel-{winners[0]}", False)
            service.debit_actual(db, tenant_id, "same-receipt", 2600, "actual", {})
            db.commit()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(settle, range(8)))
    with SessionLocal() as db:
        wallet = service.lock_wallet(db, tenant_id)
        assert service.available(wallet) == -600
        assert wallet.frozen_paid_cents + wallet.frozen_bonus_cents == 0
    try:
        command.downgrade(config, "20260911_0022")
    except Exception:
        pass
    else:
        raise AssertionError("Must not downgrade away outstanding debt")
    with SessionLocal() as db:
        wallet = service.lock_wallet(db, tenant_id)
        assert wallet.paid_cents == -600
        wallet.paid_cents += 601
        db.commit()
    command.downgrade(config, "20260911_0022")
    command.upgrade(config, "head")
    with SessionLocal() as db:
        assert service.available(service.lock_wallet(db, tenant_id)) == 1
    print("PASS: migrations preserve balances; 8 concurrent holds admit exactly one;")
    print("8 settlements debit once; debt survives rejected downgrade and credits offset it")


if __name__ == "__main__":
    main()

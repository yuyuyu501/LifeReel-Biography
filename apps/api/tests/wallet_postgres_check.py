"""Run only against a disposable PostgreSQL database, never the application DB."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from alembic.config import Config
from sqlalchemy import func, select

from alembic import command
from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError
from lifereel_api.main import app  # noqa: F401
from lifereel_api.modules.billing import service
from lifereel_api.modules.billing.models import Charge, LedgerEntry
from lifereel_api.modules.identity.models import Tenant


def main():
    assert "@lifereel-wallet-pg:5432/wallet_test" in get_settings().database_url
    command.upgrade(Config("alembic.ini"), "head")
    tenant = uuid4()
    with SessionLocal() as db:
        db.add(Tenant(id=tenant, name="Wallet concurrency QA", slug=str(tenant)))
        db.commit()

    def reserve(key):
        with SessionLocal() as db:
            try:
                charge = service.reserve(db, tenant, key, 600, "video", "QA only", {})
                db.commit()
                return str(charge.id)
            except ApiError:
                db.rollback()
                return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        same = list(pool.map(reserve, ["same"] * 8))
    assert len(set(same)) == 1 and same[0]
    with SessionLocal() as db:
        wallet = service.lock_wallet(db, tenant)
        assert service.available(wallet) == 1400
        service.transition(db, tenant, "same", False)
        db.commit()
    with ThreadPoolExecutor(max_workers=5) as pool:
        different = list(pool.map(reserve, [f"different-{index}" for index in range(5)]))
    assert sum(item is not None for item in different) == 3
    with SessionLocal() as db:
        wallet = service.lock_wallet(db, tenant)
        assert service.available(wallet) == 200
        charges = list(
            db.scalars(
                select(Charge).where(Charge.tenant_id == tenant, Charge.status == "reserved")
            )
        )
        for charge in charges:
            service.transition(db, tenant, charge.business_key, True)
            service.transition(db, tenant, charge.business_key, True)
        db.commit()
        wallet = service.lock_wallet(db, tenant)
        assert wallet.bonus_cents == 200 and wallet.frozen_bonus_cents == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(LedgerEntry)
                .where(LedgerEntry.tenant_id == tenant, LedgerEntry.event == "bonus")
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(LedgerEntry)
                .where(LedgerEntry.tenant_id == tenant, LedgerEntry.event == "consume")
            )
            == 3
        )
    print(
        "PostgreSQL migrations + concurrent welcome grant + duplicate freeze + "
        "overspend protection + duplicate settlement: PASS"
    )


if __name__ == "__main__":
    main()

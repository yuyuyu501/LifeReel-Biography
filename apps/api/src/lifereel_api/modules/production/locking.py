from contextlib import contextmanager
from threading import Lock
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_local_lock = Lock()


@contextmanager
def execution_lock(db: Session, run_id: UUID):
    # A dedicated connection holds the lock across checkpoint commits.
    engine = db.get_bind()
    if engine.dialect.name != "postgresql":
        acquired = _local_lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                _local_lock.release()
        return
    key = run_id.int % (2**63 - 1)
    with engine.connect() as connection:
        acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})

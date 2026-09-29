from contextlib import contextmanager
from threading import Lock
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_local_lock = Lock()
_local_keys: dict[UUID, tuple[Lock, int]] = {}


@contextmanager
def execution_lock(db: Session, run_id: UUID):
    # A dedicated connection holds the lock across checkpoint commits.
    engine = db.get_bind()
    if engine.dialect.name != "postgresql":
        with _local_lock:
            lock, users = _local_keys.get(run_id, (Lock(), 0))
            _local_keys[run_id] = (lock, users + 1)
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()
            with _local_lock:
                _, users = _local_keys[run_id]
                if users == 1:
                    del _local_keys[run_id]
                else:
                    _local_keys[run_id] = (lock, users - 1)
        return
    key = run_id.int % (2**63 - 1)
    with engine.connect() as connection:
        acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})

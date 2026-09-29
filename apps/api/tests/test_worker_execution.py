from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "workers" / "runtime"))
    module = import_module("execution")

    @contextmanager
    def session():
        yield object()

    monkeypatch.setattr(module, "SessionLocal", session)
    return module


@pytest.mark.parametrize(
    "status,expected",
    [("completed", 1), ("failed", 1), ("cancelled", 1), ("running", 0), ("queued", 0)],
)
def test_releases_only_terminal_results(worker, monkeypatch, status, expected):
    released = []
    monkeypatch.setattr(worker, "renew", lambda *args: None)
    monkeypatch.setattr(worker, "execute_claim", lambda *args: {"status": status})
    monkeypatch.setattr(worker, "release", lambda *args: released.append(args))
    claim = {"job_id": str(uuid4()), "token": str(uuid4())}
    assert worker.process_claim(claim, lambda: None) == {"status": status}
    assert len(released) == expected


def test_uncertain_execution_preserves_lease(worker, monkeypatch):
    released = []

    def failed(*args):
        raise ConnectionError("DB response lost")

    monkeypatch.setattr(worker, "renew", lambda *args: None)
    monkeypatch.setattr(worker, "execute_claim", failed)
    monkeypatch.setattr(worker, "release", lambda *args: released.append(args))
    with pytest.raises(ConnectionError):
        worker.process_claim({"job_id": str(uuid4()), "token": str(uuid4())}, lambda: None)
    assert released == []


def test_slow_local_execution_renews_independently(worker, monkeypatch):
    executing, renewed, finished = Event(), Event(), Event()

    def renew(job, token, done, touch):
        assert executing.wait(2)
        renewed.set()
        assert done.wait(2)
        finished.set()

    def execute(*args):
        executing.set()
        assert renewed.wait(2)
        return {"status": "completed"}

    monkeypatch.setattr(worker, "renew", renew)
    monkeypatch.setattr(worker, "execute_claim", execute)
    monkeypatch.setattr(worker, "release", lambda *args: None)
    worker.process_claim({"job_id": str(uuid4()), "token": str(uuid4())}, lambda: None)
    assert renewed.is_set() and finished.is_set()


def test_lost_ownership_stops_renewing(worker, monkeypatch):
    class Done:
        def wait(self, seconds):
            return False

    monkeypatch.setattr(worker, "heartbeat", lambda *args: {"owned": False})

    def touch():
        pytest.fail("Lost lease must not report healthy ownership")

    worker.renew(uuid4(), uuid4(), Done(), touch)

import importlib
from pathlib import Path
from threading import Event

import httpx
import pytest


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "worker" / "src"))
    return importlib.import_module("lifereel_worker.main")


def test_worker_timeout_preserves_lease_without_reporting_false_failure(worker, monkeypatch):
    paths = []

    def transport(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/execute"):
            raise httpx.ReadTimeout("lost response")
        return httpx.Response(200, json={"owned": True})

    monkeypatch.setattr(worker, "renew", lambda *args: None)
    settings = worker.Settings(api_access_key="test")
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        worker.process_claim(client, settings, "interview", {"job_id": "job", "token": "token"})
    assert paths == ["/v1/internal/worker/job/execute"]


@pytest.mark.parametrize("status,release", [("completed", True), ("failed", True),
                                            ("running", False), ("queued", False)])
@pytest.mark.parametrize("lane,seconds", [("interview", 1200), ("video", 2400)])
def test_worker_waits_for_configured_lane_and_releases_only_terminal_result(
    worker, monkeypatch, status, release, lane, seconds,
):
    paths = []

    def transport(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/execute"):
            assert request.extensions["timeout"] == {
                "connect": 10, "read": seconds, "write": 30, "pool": 10,
            }
        return httpx.Response(200, json={"status": status, "owned": True})

    monkeypatch.setattr(worker, "renew", lambda *args: None)
    settings = worker.Settings(
        api_access_key="test", worker_interview_timeout_seconds=1200,
        worker_video_timeout_seconds=2400,
    )
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        worker.process_claim(client, settings, lane, {"job_id": "job", "token": "token"})
    assert len(paths) == (2 if release else 1)


def test_worker_consumes_only_its_assigned_lane(worker, monkeypatch):
    stop = Event()
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"job_id": "job", "token": "token"}

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, json):
            calls.append(json)
            return Response()

    monkeypatch.setattr(worker.httpx, "Client", Client)
    monkeypatch.setattr(worker, "process_claim", lambda *args: stop.set())
    worker.consume(worker.Settings(api_access_key="test"), "video", stop)
    assert calls == [{"lane": "video"}]


def test_slow_execute_renews_lease_independently(worker, monkeypatch):
    executing, renewed, finished = Event(), Event(), Event()

    def renew(settings, claim, done):
        # Synchronize threads instead of waiting a real lease period or calling a provider.
        assert executing.wait(2)
        renewed.set()
        assert done.wait(2)
        finished.set()

    def transport(request):
        if request.url.path.endswith("/execute"):
            executing.set()
            assert renewed.wait(2), "heartbeat was blocked by the execute request"
        return httpx.Response(200, json={"status": "completed", "owned": True})

    monkeypatch.setattr(worker, "renew", renew)
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        worker.process_claim(client, worker.Settings(api_access_key="test"), "interview",
                             {"job_id": "job", "token": "token"})
    assert renewed.is_set() and finished.is_set()


@pytest.mark.parametrize("value", [float("inf"), float("nan"), 0, 14401])
def test_worker_waits_have_finite_bounds(worker, value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        worker.Settings(api_access_key="test", worker_interview_timeout_seconds=value)

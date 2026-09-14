import importlib
from pathlib import Path
from threading import Event

import httpx
import pytest


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "worker" / "src"))
    return importlib.import_module("lifereel_worker.main")


def test_worker_timeout_releases_lease_without_reporting_false_failure(worker, monkeypatch):
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
    assert paths == ["/v1/internal/worker/job/execute", "/v1/internal/worker/job/release"]


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

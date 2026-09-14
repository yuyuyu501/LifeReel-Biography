"""No paid APIs. Only run against the disposable capacity_test database."""

import json
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Lock
from uuid import UUID, uuid4

import httpx
from alembic.config import Config
from sqlalchemy import select

from alembic import command
from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal, engine
from lifereel_api.main import app  # noqa: F401
from lifereel_api.modules.identity.models import Tenant
from lifereel_api.modules.jobs.dispatch import claim_job
from lifereel_api.modules.jobs.models import Job


def main():
    settings = get_settings()
    assert settings.database_url.endswith(":55434/capacity_test")
    assert settings.app_env == "test" and settings.llm_provider == "mock"
    command.upgrade(Config("alembic.ini"), "head")
    tenant = uuid4()
    with SessionLocal() as db:
        db.add(Tenant(id=tenant, name="Isolated capacity test", slug=str(tenant)))
        db.commit()
        for kind, count in (("interview.turn.process", 10), ("production.render", 2)):
            db.add_all(Job(tenant_id=tenant, kind=kind, payload={}) for _ in range(count))
        db.commit()

    def claim(_):
        with SessionLocal() as db:
            return claim_job(db, "interview")

    with ThreadPoolExecutor(max_workers=10) as pool:
        claims = [c for c in pool.map(claim, range(10)) if c]
    assert len(claims) == 3 and len({c["job_id"] for c in claims}) == 3
    with SessionLocal() as db:
        assert claim_job(db, "video") is not None
        assert claim_job(db, "video") is None
        for job in db.scalars(select(Job).where(Job.tenant_id == tenant)):
            job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    completed = set()
    peak = {"interview": 0, "video": 0}
    active = {"interview": 0, "video": 0}
    mutex = Lock()

    def consumer(lane):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with SessionLocal() as db:
                item = claim_job(db, lane)
                if item is None:
                    return
                identity = UUID(item["job_id"])
                with mutex:
                    assert identity not in completed
                    active[lane] += 1
                    peak[lane] = max(peak[lane], active[lane])
                time.sleep(0.15 if lane == "interview" else 0.6)
                job = db.get(Job, identity)
                job.status = "completed"
                db.commit()
                with mutex:
                    active[lane] -= 1
                    completed.add(identity)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(consumer, ["interview"] * 3 + ["video"]))
    assert len(completed) == 12 and peak == {"interview": 3, "video": 1}

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "lifereel_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
            "--log-level",
            "warning",
        ]
    )
    try:
        base = f"http://127.0.0.1:{port}"
        with httpx.Client(
            base_url=base,
            timeout=30,
            trust_env=False,
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=100,
            ),
        ) as client:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Capacity HTTP server stopped")
                try:
                    if client.get("/ready").status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(0.1)

            def read(index):
                started = time.monotonic()
                response = client.get(["/v1/persons", "/v1/chapters"][index % 2])
                assert response.status_code == 200, response.status_code
                return time.monotonic() - started

            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=100) as pool:
                times = sorted(pool.map(read, range(300)))
            print(
                json.dumps(
                    {
                        "jobs_completed_once": len(completed),
                        "peak": peak,
                        "http_concurrency": 100,
                        "http_requests": 300,
                        "http_elapsed_seconds": round(time.monotonic() - started, 2),
                        "http_p95_ms": round(times[int(len(times) * 0.95)] * 1000),
                        "note": "Local synthetic test; no cloud model throughput measured",
                    }
                )
            )
    finally:
        process.terminate()
        process.wait(timeout=15)
        engine.dispose()


if __name__ == "__main__":
    main()

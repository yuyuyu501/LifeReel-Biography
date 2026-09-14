from __future__ import annotations

import hashlib
import hmac
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Thread
from typing import Any

import httpx
import structlog
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")
    api_internal_url: str = "http://api:8000"
    api_access_key: str
    interview_concurrency: int = Field(default=3, ge=1, le=8)
    video_concurrency: int = Field(default=1, ge=1, le=4)
    worker_poll_seconds: float = Field(default=2, ge=0.1, le=30)
    worker_heartbeat_seconds: float = Field(default=20, ge=1, le=30)

    @property
    def headers(self):
        return {
            "X-Worker-Key": hmac.new(
                self.api_access_key.encode(),
                b"lifereel-worker-v1",
                hashlib.sha256,
            ).hexdigest()
        }


log = structlog.get_logger()


def renew(settings: Settings, claim: dict, done: Event):
    url = f"{settings.api_internal_url}/v1/internal/worker/{claim['job_id']}/heartbeat"
    with httpx.Client(headers=settings.headers, timeout=10, trust_env=False) as client:
        while not done.wait(settings.worker_heartbeat_seconds):
            try:
                response = client.post(url, json={"token": claim["token"]})
                response.raise_for_status()
                if not response.json()["owned"]:
                    log.warning("job.lease_lost", job_id=claim["job_id"])
                    return
            except Exception as exc:
                log.warning(
                    "job.heartbeat_failed", job_id=claim["job_id"], error=type(exc).__name__
                )


def process_claim(client: httpx.Client, settings: Settings, lane: str, claim: dict):
    base = f"{settings.api_internal_url}/v1/internal/worker/{claim['job_id']}"
    done = Event()
    heartbeat = Thread(target=renew, args=(settings, claim, done), daemon=True)
    heartbeat.start()
    try:
        response = client.post(
            f"{base}/execute",
            json={"token": claim["token"]},
            timeout=httpx.Timeout(1800 if lane == "video" else 900, connect=10),
        )
        response.raise_for_status()
        log.info("job.result", job_id=claim["job_id"], status=response.json()["status"])
    except Exception as exc:
        # A lost HTTP response is not evidence of failure. Database state wins.
        log.warning("job.delivery_uncertain", job_id=claim["job_id"], error=type(exc).__name__)
    finally:
        done.set()
        heartbeat.join(timeout=12)
        try:
            response = client.post(f"{base}/release", json={"token": claim["token"]}, timeout=10)
            response.raise_for_status()
        except Exception as exc:
            log.warning("job.release_pending", job_id=claim["job_id"], error=type(exc).__name__)


def consume(settings: Settings, lane: str, stopping: Event):
    with httpx.Client(headers=settings.headers, timeout=15, trust_env=False) as client:
        while not stopping.is_set():
            try:
                response = client.post(
                    f"{settings.api_internal_url}/v1/internal/worker/claim",
                    json={"lane": lane},
                )
                response.raise_for_status()
                claim = response.json()
                if claim:
                    process_claim(client, settings, lane, claim)
                    continue
            except Exception as exc:
                log.warning("queue.poll_failed", lane=lane, error=type(exc).__name__)
            stopping.wait(settings.worker_poll_seconds)


def run() -> None:
    settings = Settings()
    stopping = Event()

    def stop(*_: Any):
        stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    lanes = ["interview"] * settings.interview_concurrency + ["video"] * settings.video_concurrency
    log.info(
        "worker.started", interview=settings.interview_concurrency, video=settings.video_concurrency
    )
    with ThreadPoolExecutor(max_workers=len(lanes), thread_name_prefix="lifereel") as pool:
        futures = [pool.submit(consume, settings, lane, stopping) for lane in lanes]
        while not stopping.wait(2):
            if any(f.done() for f in futures):
                stopping.set()
                raise RuntimeError("WORKER_CONSUMER_STOPPED")
            Path("/tmp/lifereel-worker-heartbeat").write_text(str(time.time()), encoding="ascii")
    log.info("worker.stopped")


if __name__ == "__main__":
    run()

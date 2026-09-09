from __future__ import annotations

import json
import signal
from typing import Any

import httpx
import redis
import structlog
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")
    redis_url: str = "redis://localhost:6379/0"
    worker_queue: str = "lifereel:jobs"
    api_internal_url: str = "http://api:8000"
    api_access_key: str


log = structlog.get_logger()
running = True


def stop(*_: Any) -> None:
    global running
    running = False


def handle(payload: dict[str, Any], settings: Settings) -> None:
    required = {"job_id", "tenant_id", "kind", "payload"}
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError("WORKER_JOB_ENVELOPE_INVALID")
    log.info(
        "job.received",
        kind=payload["kind"],
        job_id=payload["job_id"],
        tenant_id=payload["tenant_id"],
    )
    # Provider handlers remain idempotent and report final state through the API job ledger.
    if payload["kind"] not in {
        "production.render",
        "asr.transcribe",
        "interview.turn.process",
    }:
        raise ValueError("WORKER_JOB_KIND_UNSUPPORTED")
    if payload["kind"] == "interview.turn.process":
        workflow_id = payload["payload"]["workflow_id"]
        response = httpx.post(
            f"{settings.api_internal_url}/v1/internal/interview-turns/{workflow_id}/execute",
            headers={
                "X-API-Key": settings.api_access_key,
                "X-Tenant-ID": payload["tenant_id"],
            },
            timeout=600,
        )
        response.raise_for_status()
        return
    if payload["kind"] == "production.render":
        project_id = payload["payload"]["project_id"]
        runs = httpx.get(
            f"{settings.api_internal_url}/v1/production/runs",
            headers={
                "X-API-Key": settings.api_access_key,
                "X-Tenant-ID": payload["tenant_id"],
            },
            timeout=30,
        )
        runs.raise_for_status()
        run = next(
            item
            for item in runs.json()
            if item["project_id"] == project_id and item["job_id"] == payload["job_id"]
        )
        response = httpx.post(
            f"{settings.api_internal_url}/v1/production/runs/{run['id']}/execute",
            headers={
                "X-API-Key": settings.api_access_key,
                "X-Tenant-ID": payload["tenant_id"],
            },
            timeout=1200,
        )
        response.raise_for_status()


def report_failure(payload: dict[str, Any], settings: Settings, exc: Exception) -> None:
    try:
        response = httpx.post(
            f"{settings.api_internal_url}/v1/jobs/{payload['job_id']}/fail",
            headers={
                "X-API-Key": settings.api_access_key,
                "X-Tenant-ID": payload["tenant_id"],
            },
            json={"error_code": "WORKER_ERROR"},
            timeout=30,
        )
        response.raise_for_status()
    except Exception:
        log.exception("job.failure_report_failed", job_id=payload.get("job_id"))


def run() -> None:
    settings = Settings()
    client = redis.from_url(settings.redis_url, decode_responses=True)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    log.info("worker.started", queue=settings.worker_queue)
    while running:
        item = client.blpop(settings.worker_queue, timeout=2)
        if not item:
            continue
        _, raw = item
        payload: dict[str, Any] | None = None
        try:
            payload = json.loads(raw)
            handle(payload, settings)
        except Exception as exc:
            log.exception("job.failed", payload=raw)
            if payload and {"job_id", "tenant_id"} <= payload.keys():
                report_failure(payload, settings, exc)
    log.info("worker.stopped")


if __name__ == "__main__":
    run()

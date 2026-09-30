"""Execute domain work in the worker process, with fenced database leases."""

import json
import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock

from execution import process_claim
from lifereel_api.architecture.metadata import register_models
from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.jobs.dispatch import claim_job


def run(role):
    if role not in {"interview", "media", "book"}:
        raise ValueError("INVALID_WORKER_ROLE")
    os.environ["LIFEREEL_SERVICE"] = f"worker-{role}"
    register_models()
    settings = get_settings()
    lane = {"interview": "interview", "media": "video", "book": "book"}[role]
    count = {"interview": settings.interview_concurrency,
             "media": settings.video_concurrency, "book": 1}[role]
    stop = Event()
    state = {}
    mutex = Lock()

    def touch(slot):
        with mutex:
            state[slot] = time.time()

    def consume(slot):
        while not stop.is_set():
            try:
                with SessionLocal() as db:
                    claim = claim_job(db, lane)
                touch(slot)
                if claim:
                    result = process_claim(claim, lambda: touch(slot))
                    print(
                        json.dumps(
                            {
                                "event": "job.result",
                                "service": f"worker-{role}",
                                "job_id": claim["job_id"],
                                **result,
                            }
                        ),
                        flush=True,
                    )
            except Exception as exc:
                print(
                    json.dumps({"event": "worker.failure", "error": type(exc).__name__}), flush=True
                )
            stop.wait(2)

    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    with ThreadPoolExecutor(max_workers=count) as executor:
        futures = [executor.submit(consume, i) for i in range(count)]
        while not stop.wait(2):
            if any(f.done() for f in futures):
                stop.set()
                raise RuntimeError("WORKER_CONSUMER_STOPPED")
            with mutex:
                healthy = len(state) == count and all(
                    time.time() - stamp < 55 for stamp in state.values()
                )
            if healthy:
                Path("/tmp/lifereel-worker-heartbeat").write_text(
                    str(time.time()), encoding="ascii"
                )

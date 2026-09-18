from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

import redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from lifereel_api.api import api_router
from lifereel_api.core.config import get_settings
from lifereel_api.core.database import Base, SessionLocal, engine
from lifereel_api.core.errors import install_error_handlers
from lifereel_api.core.seed import seed_foundation
from lifereel_api.modules.auth import models as auth_models  # noqa: F401
from lifereel_api.modules.billing import models as billing_models  # noqa: F401
from lifereel_api.modules.evidence import models as evidence_models  # noqa: F401
from lifereel_api.modules.governance import models as governance_models  # noqa: F401
from lifereel_api.modules.identity import models as identity_models  # noqa: F401
from lifereel_api.modules.interview import models as interview_models  # noqa: F401
from lifereel_api.modules.interview.voice_router import socket_router
from lifereel_api.modules.interview.voice_service import recover_stale
from lifereel_api.modules.jobs import models as job_models  # noqa: F401
from lifereel_api.modules.jobs.dispatch import router as worker_router
from lifereel_api.modules.memory import models as memory_models  # noqa: F401
from lifereel_api.modules.orchestration import service as orchestration_service  # noqa: F401
from lifereel_api.modules.production import models as production_models  # noqa: F401
from lifereel_api.modules.production import (
    reference_models as production_reference_models,  # noqa: F401
)
from lifereel_api.modules.production import references as production_references  # noqa: F401
from lifereel_api.modules.publication import models as publication_models  # noqa: F401
from lifereel_api.modules.restoration import models as restoration_models  # noqa: F401
from lifereel_api.modules.script import models as script_models  # noqa: F401

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            seed_foundation(db)
    async def recover_voice_calls():
        while True:
            try:
                await run_in_threadpool(recover_stale)
            except Exception as exc:
                logging.getLogger(__name__).warning("Voice recovery: %s", type(exc).__name__)
            await asyncio.sleep(15)

    recovery = asyncio.create_task(recover_voice_calls())
    try:
        yield
    finally:
        recovery.cancel()
        with suppress(asyncio.CancelledError):
            await recovery


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Evidence-first oral-history interview and biography production API.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_error_handlers(app)
app.include_router(api_router)
app.include_router(worker_router)
app.include_router(socket_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "lifereel-api", "environment": settings.app_env}


@app.get("/ready", tags=["system"])
def ready() -> dict[str, str]:
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
    return {"status": "ready"}


@app.get("/system-status", tags=["system"])
def system_status() -> dict:
    checks: dict[str, dict[str, str]] = {}
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "error", "detail": type(exc).__name__}
    try:
        redis.from_url(settings.redis_url).ping()
        checks["redis"] = {"status": "ok"}
    except Exception as exc:
        checks["redis"] = {"status": "unavailable", "detail": type(exc).__name__}
    checks["storage"] = {"status": "configured", "backend": settings.storage_backend}
    checks["providers"] = {
        "llm": settings.llm_provider,
        "asr": settings.asr_provider,
        "image": settings.image_provider,
        "video": settings.video_provider,
        "voice": settings.voice_provider,
        "models": {
            "interview": settings.model_for("interview") or None,
            "memory": settings.model_for("memory") or None,
            "script": settings.model_for("script") or None,
            "vision": settings.model_for("vision") or None,
            "asr": settings.model_for("asr") or None,
        },
    }
    return {
        "status": "ok" if checks["database"]["status"] == "ok" else "degraded",
        "checks": checks,
    }

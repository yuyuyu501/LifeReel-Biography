"""One owned API per process. Schema migration is a separate release step."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from importlib import import_module

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from lifereel_api.architecture.metadata import register_models
from lifereel_api.architecture.topology import ROUTERS
from lifereel_api.core.config import get_settings
from lifereel_api.core.database import engine
from lifereel_api.core.errors import install_error_handlers
from lifereel_api.core.security import require_api_access
from lifereel_api.modules.auth.dependencies import enforce_write_role


def create_app(name: str) -> FastAPI:
    if name not in ROUTERS:
        raise ValueError("UNKNOWN_SERVICE")
    register_models()

    @asynccontextmanager
    async def lifespan(app):
        async def maintain():
            while True:
                try:
                    if name == "interview":
                        from lifereel_api.modules.interview.voice_service import recover_stale

                        await run_in_threadpool(recover_stale)
                    elif name == "tasks":
                        from lifereel_api.modules.jobs.outbox import dispatch_batch

                        await run_in_threadpool(dispatch_batch)
                except Exception as exc:
                    logging.getLogger(__name__).warning(
                        "maintenance.%s.%s", name, type(exc).__name__
                    )
                await asyncio.sleep(2 if name == "tasks" else 15)

        task = asyncio.create_task(maintain()) if name in {"interview", "tasks"} else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title=f"LifeReel {name}", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.service = name
    install_error_handlers(app)
    api = APIRouter(
        prefix="/v1",
        dependencies=[
            Depends(require_api_access),
            Depends(enforce_write_role),
        ],
    )
    for module in ROUTERS[name]:
        api.include_router(import_module(f"lifereel_api.modules.{module}").router)
    if name == "model-gateway":
        api.include_router(import_module("lifereel_api.providers.router").router)
    app.include_router(api)
    if name == "interview":
        app.include_router(
            import_module("lifereel_api.modules.interview.voice_router").socket_router
        )
    if name == "tasks":
        from lifereel_api.modules.jobs.dispatch import router

        app.include_router(router)
    from lifereel_api.architecture.internal import router_for

    app.include_router(router_for(name))

    if name == "tasks":

        async def service_checks():
            import httpx

            from lifereel_api.architecture.topology import service_url

            async def probe(client, target):
                try:
                    response = await client.get(service_url(target) + "/ready")
                    return target, response.status_code == 200
                except httpx.RequestError:
                    return target, False

            async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
                checks = dict(await asyncio.gather(*(probe(client, target) for target in ROUTERS)))
            return checks

        @app.get("/cluster-ready")
        async def cluster_ready():
            checks = await service_checks()
            return JSONResponse(
                {"status": "ready" if all(checks.values()) else "degraded", "services": checks},
                status_code=200 if all(checks.values()) else 503,
            )

        @app.get("/cluster-status")
        async def cluster_status():
            from lifereel_api.architecture.status import system_status

            status, checks = await asyncio.gather(
                run_in_threadpool(system_status), service_checks()
            )
            status["services"] = checks
            if not all(checks.values()):
                status["status"] = "degraded"
            return status

    @app.get("/health")
    def health():
        return {"status": "ok", "service": name}

    @app.get("/ready")
    def ready():
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
        except Exception:
            return JSONResponse({"status": "unavailable", "service": name}, status_code=503)
        return {"status": "ready", "service": name}

    return app

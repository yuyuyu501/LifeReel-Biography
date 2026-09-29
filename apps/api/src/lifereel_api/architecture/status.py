"""Public status contract shared by the compatibility app and task service."""

import redis

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import engine


def system_status():
    settings = get_settings()
    checks = {}
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "error", "detail": type(exc).__name__}
    try:
        with redis.from_url(
            settings.redis_url, socket_connect_timeout=3, socket_timeout=3
        ) as client:
            client.ping()
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
            task: settings.model_for(task) or None
            for task in ("interview", "memory", "script", "vision", "asr")
        },
    }
    return {
        "status": "ok"
        if all(checks[key]["status"] == "ok" for key in ("database", "redis"))
        else "degraded",
        "checks": checks,
    }

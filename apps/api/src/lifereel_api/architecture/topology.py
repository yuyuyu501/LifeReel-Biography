"""Explicit ownership used by service boot, internal clients and architecture checks."""
import os

ROUTERS = {
    "identity": ("auth.router", "identity.router", "governance.router"),
    "interview": ("interview.router", "interview.voice_router", "orchestration.router"),
    "memory": ("memory.router",),
    "script": ("script.router",),
    "media": ("evidence.router", "restoration.router", "production.router", "publication.router"),
    "billing": ("billing.router",),
    "tasks": ("jobs.router",),
    "model-gateway": (),
}


def service_name():
    return os.environ.get("LIFEREEL_SERVICE", "monolith")


def distributed():
    return os.environ.get("SERVICE_MODE", "local") == "distributed"


def is_remote(owner):
    return distributed() and service_name() not in {owner, f"worker-{owner}"}


def service_url(owner):
    if owner not in ROUTERS:
        raise ValueError("UNKNOWN_SERVICE")
    return os.environ.get(owner.upper().replace("-", "_") + "_URL", f"http://{owner}:8000")

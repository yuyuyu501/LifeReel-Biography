"""Shared relational metadata; imports declarations, never application routers."""
from importlib import import_module

MODULES = (
    "auth.models", "identity.models", "governance.models", "interview.models",
    "billing.models", "evidence.models", "jobs.models", "jobs.events", "memory.models",
    "production.models", "production.reference_models", "publication.models",
    "restoration.models", "script.models", "book.models",
)


def register_models():
    import_module("lifereel_api.providers.models")
    for module in MODULES:
        import_module(f"lifereel_api.modules.{module}")

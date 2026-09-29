"""Reject a draft if its source snapshot changed while a provider was running."""

from contextvars import ContextVar

is_current = ContextVar("script_is_current", default=lambda: True)
remote_guard = ContextVar("script_remote_guard", default=None)


def revision_key(tenant_id, call_id):
    return f"lifereel:voice-revision:{tenant_id}:{call_id}"

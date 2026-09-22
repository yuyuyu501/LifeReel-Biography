"""Reject a draft if its source snapshot changed while a provider was running."""

from contextvars import ContextVar

is_current = ContextVar("script_is_current", default=lambda: True)

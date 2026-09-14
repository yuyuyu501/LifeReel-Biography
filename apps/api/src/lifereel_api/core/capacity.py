"""Process-local limits: production deliberately runs ONE API process."""

import time
from contextlib import contextmanager
from functools import lru_cache, wraps
from threading import BoundedSemaphore, Lock

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode

_rate_lock = Lock()
_last_request = 0.0


@lru_cache(maxsize=16)
def semaphore(name, limit):
    return BoundedSemaphore(limit)


@contextmanager
def resource(name):
    settings = get_settings()
    gate = semaphore(name, settings.llm_concurrency if name == "llm" else 1)
    if not gate.acquire(timeout=settings.resource_wait_seconds):
        raise ApiError(503, ErrorCode.RESOURCE_BUSY)
    try:
        if name == "llm":
            global _last_request
            with _rate_lock:
                delay = settings.llm_min_interval_seconds - (time.monotonic() - _last_request)
                if delay > 0:
                    time.sleep(delay)
                _last_request = time.monotonic()
        yield
    finally:
        gate.release()


def limited(name):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with resource(name):
                return function(*args, **kwargs)

        return wrapped

    return decorate

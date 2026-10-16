"""Bounded provider failover; business validation stays with the caller."""

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass

import httpx

from lifereel_api.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class Circuit:
    failures: int = 0
    open_until: float = 0
    probing: bool = False


_circuits: dict[tuple, Circuit] = {}
_lock = threading.Lock()


def retry_reason(exc):
    from lifereel_api.providers.openai_compatible import (
        ProviderHTTPError,
        ProviderPolicyError,
        ProviderStreamError,
    )

    if isinstance(exc, ProviderPolicyError):
        return None
    if isinstance(exc, ProviderStreamError):
        return "stream"
    if isinstance(exc, json.JSONDecodeError):
        return "response"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.RequestError):
        return "transport"
    if isinstance(exc, ProviderHTTPError):
        status = exc.response.status_code
        if status == 400 and exc.response_format_unsupported:
            return "unsupported_response_format"
        if status in {404, 408, 429} or status >= 500:
            return f"http_{status}"
    return None


def uncertain(exc):
    """An explicit rejection cannot erase an earlier possibly billed attempt."""
    if getattr(exc, "pool_uncertain", False):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code not in {400, 401, 403, 404, 413, 422, 429}
    return isinstance(exc, (httpx.RequestError, json.JSONDecodeError))


def _acquire(key):
    with _lock:
        circuit = _circuits.setdefault(key, Circuit())
        if circuit.open_until:
            if circuit.open_until > time.monotonic() or circuit.probing:
                return False
            circuit.probing = True
        return True


def _finish(key, failed):
    settings = get_settings()
    with _lock:
        circuit = _circuits[key]
        circuit.probing = False
        if not failed:
            circuit.failures = 0
            circuit.open_until = 0
        else:
            circuit.failures += 1
            if circuit.failures >= settings.llm_model_pool_failure_threshold:
                circuit.open_until = time.monotonic() + settings.llm_model_pool_cooldown_seconds


def chat(client, messages, *, task, **kwargs):
    from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

    settings = get_settings()
    pool = settings.model_pool_for(task)
    if client.model != pool[0][1]:
        raise ValueError("llm_model_pool_primary_mismatch")
    total = settings.llm_model_pool_total_seconds
    if task in {"interview", "interview_review"}:
        total = min(total, settings.interview_turn_budget_seconds - 10)
    deadline = time.monotonic() + total
    attempts, last_error, had_uncertainty = [], None, False
    client.last_pool_attempts = attempts
    for index, (provider, model) in enumerate(pool):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or len(attempts) >= settings.llm_model_pool_max_attempts:
            break
        base, key = settings.llm_endpoint_for_provider(provider)
        if not base or not key:
            continue
        scope = hashlib.sha256(key.encode()).hexdigest()
        circuit_key = (provider, model, base, scope)
        if not _acquire(circuit_key):
            continue
        candidate = OpenAICompatibleClient(base, key, model, task=task, provider=provider)
        attempt = {"provider": provider, "model": model}
        attempts.append(attempt)
        try:
            output = candidate._single_chat(
                messages, task=task,
                time_budget=min(remaining, settings.llm_model_pool_attempt_seconds), **kwargs,
            )
        except Exception as exc:
            reason = retry_reason(exc)
            _finish(circuit_key, reason is not None)
            had_uncertainty = had_uncertainty or uncertain(exc)
            attempt.update(status="failed", reason=reason or "terminal")
            exc.pool_uncertain = had_uncertainty
            exc.pool_attempts = list(attempts)
            last_error = exc
            if reason is None:
                raise
            logger.warning("llm.pool_failed task=%s provider=%s model=%s reason=%s",
                           task, provider, model, reason)
        else:
            _finish(circuit_key, False)
            attempt["status"] = "succeeded"
            client.last_model_used, client.last_provider_used = model, provider
            client.fallback_used = index > 0
            return output
    if last_error:
        raise last_error
    from lifereel_api.core.errors import ApiError, ErrorCode

    raise ApiError(503, ErrorCode.INTERVIEW_LLM_CONFIGURATION_INCOMPLETE)

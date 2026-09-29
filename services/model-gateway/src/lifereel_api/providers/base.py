from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderCapabilities:
    name: str
    kinds: tuple[str, ...]
    configured: bool
    supports_webhooks: bool = False
    supports_cancel: bool = False


@dataclass
class ProviderRequest:
    kind: str
    inputs: dict[str, Any]
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderSubmission:
    provider_job_id: str
    status: str
    raw: dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    def capabilities(self) -> ProviderCapabilities: ...

    def estimate(self, request: ProviderRequest) -> float: ...

    def submit(self, request: ProviderRequest, idempotency_key: str) -> ProviderSubmission: ...

    def get_status(self, provider_job_id: str) -> ProviderSubmission: ...

    def cancel(self, provider_job_id: str) -> ProviderSubmission: ...

    def fetch_outputs(self, provider_job_id: str) -> list[dict[str, Any]]: ...

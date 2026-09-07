from __future__ import annotations

import hashlib
import json

from lifereel_api.providers.base import (
    ProviderCapabilities,
    ProviderRequest,
    ProviderSubmission,
)


class MockProvider:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._jobs: dict[str, ProviderSubmission] = {}

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name=f"mock-{self.kind}",
            kinds=(self.kind,),
            configured=True,
            supports_cancel=True,
        )

    def estimate(self, request: ProviderRequest) -> float:
        return 0.0

    def submit(self, request: ProviderRequest, idempotency_key: str) -> ProviderSubmission:
        digest = hashlib.sha256(
            json.dumps(
                {"request": request.inputs, "options": request.options, "key": idempotency_key},
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()[:24]
        submission = ProviderSubmission(
            provider_job_id=digest,
            status="completed",
            raw={"kind": self.kind, "mock": True},
        )
        self._jobs[digest] = submission
        return submission

    def get_status(self, provider_job_id: str) -> ProviderSubmission:
        return self._jobs.get(
            provider_job_id,
            ProviderSubmission(provider_job_id=provider_job_id, status="not_found"),
        )

    def cancel(self, provider_job_id: str) -> ProviderSubmission:
        submission = ProviderSubmission(provider_job_id=provider_job_id, status="cancelled")
        self._jobs[provider_job_id] = submission
        return submission

    def fetch_outputs(self, provider_job_id: str) -> list[dict]:
        status = self.get_status(provider_job_id)
        return (
            [{"provider_job_id": provider_job_id, "kind": self.kind}]
            if status.status == "completed"
            else []
        )

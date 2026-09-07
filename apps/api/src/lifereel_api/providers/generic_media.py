from __future__ import annotations

from typing import Any

import httpx

from lifereel_api.providers.base import (
    ProviderCapabilities,
    ProviderRequest,
    ProviderSubmission,
)


class GenericAsyncMediaProvider:
    """Configurable adapter for image, video and voice APIs with async job semantics."""

    def __init__(
        self,
        name: str,
        kind: str,
        base_url: str,
        api_key: str,
        submit_path: str = "/jobs",
    ) -> None:
        self.name = name
        self.kind = kind
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.submit_path = submit_path

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name=self.name,
            kinds=(self.kind,),
            configured=bool(self.base_url and self.api_key),
            supports_webhooks=True,
            supports_cancel=True,
        )

    def estimate(self, request: ProviderRequest) -> float:
        seconds = float(request.options.get("duration_seconds", 0))
        units = float(request.options.get("units", 1))
        return round(max(units, seconds / 5) * float(request.options.get("unit_price", 0)), 4)

    def submit(self, request: ProviderRequest, idempotency_key: str) -> ProviderSubmission:
        response = httpx.post(
            f"{self.base_url}{self.submit_path}",
            headers={**self.headers, "Idempotency-Key": idempotency_key},
            json={"kind": request.kind, "inputs": request.inputs, "options": request.options},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        return self._submission(payload)

    def get_status(self, provider_job_id: str) -> ProviderSubmission:
        response = httpx.get(
            f"{self.base_url}/jobs/{provider_job_id}", headers=self.headers, timeout=30
        )
        response.raise_for_status()
        return self._submission(response.json())

    def cancel(self, provider_job_id: str) -> ProviderSubmission:
        response = httpx.post(
            f"{self.base_url}/jobs/{provider_job_id}/cancel",
            headers=self.headers,
            timeout=30,
        )
        response.raise_for_status()
        return self._submission(response.json())

    def fetch_outputs(self, provider_job_id: str) -> list[dict[str, Any]]:
        response = httpx.get(
            f"{self.base_url}/jobs/{provider_job_id}/outputs",
            headers=self.headers,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else payload.get("outputs", [])

    @staticmethod
    def _submission(payload: dict[str, Any]) -> ProviderSubmission:
        job_id = payload.get("id") or payload.get("job_id") or payload.get("task_id")
        if not job_id:
            raise ValueError("VIDEO_PROVIDER_JOB_ID_MISSING")
        return ProviderSubmission(
            provider_job_id=str(job_id),
            status=str(payload.get("status", "queued")),
            raw=payload,
        )

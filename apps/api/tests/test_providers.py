from __future__ import annotations

import base64


def test_generic_video_provider_executes_async_contract(monkeypatch) -> None:
    from lifereel_api.core.config import get_settings
    from lifereel_api.modules.production.providers import GenericVideoProvider
    from lifereel_api.providers.base import ProviderSubmission
    from lifereel_api.providers.generic_media import GenericAsyncMediaProvider

    monkeypatch.setenv("MEDIA_PROVIDER_BASE_URL", "https://provider.example")
    monkeypatch.setenv("MEDIA_PROVIDER_API_KEY", "provider-secret")
    monkeypatch.setenv("MEDIA_PROVIDER_POLL_SECONDS", "0")
    get_settings.cache_clear()
    calls: list[str] = []

    def submit(self, request, idempotency_key):
        calls.append(f"submit:{request.kind}:{bool(idempotency_key)}")
        return ProviderSubmission(provider_job_id="job-1", status="queued")

    def status(self, provider_job_id):
        calls.append(f"status:{provider_job_id}")
        return ProviderSubmission(provider_job_id=provider_job_id, status="completed")

    def outputs(self, provider_job_id):
        calls.append(f"outputs:{provider_job_id}")
        return [
            {
                "mime_type": "video/mp4",
                "extension": "mp4",
                "content_base64": base64.b64encode(b"synthetic-video").decode(),
            }
        ]

    monkeypatch.setattr(GenericAsyncMediaProvider, "submit", submit)
    monkeypatch.setattr(GenericAsyncMediaProvider, "get_status", status)
    monkeypatch.setattr(GenericAsyncMediaProvider, "fetch_outputs", outputs)
    try:
        output = GenericVideoProvider("generic-media-video").render(
            "测试影传",
            [{"duration_seconds": 3, "heading": "开场"}],
        )
        assert output.content == b"synthetic-video"
        assert output.mime_type == "video/mp4"
        assert calls == ["submit:video:True", "status:job-1", "outputs:job-1"]
        assert "content_base64" not in output.parameters["output"]
    finally:
        monkeypatch.delenv("MEDIA_PROVIDER_BASE_URL", raising=False)
        monkeypatch.delenv("MEDIA_PROVIDER_API_KEY", raising=False)
        monkeypatch.delenv("MEDIA_PROVIDER_POLL_SECONDS", raising=False)
        get_settings.cache_clear()

from __future__ import annotations

import base64
import json

import httpx
import pytest


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


def _seedance_provider(monkeypatch, handler):
    from lifereel_api.core.config import get_settings
    from lifereel_api.modules.production.providers import VolcengineSeedanceProvider

    monkeypatch.setenv("VOLCENGINE_API_KEY", "test-provider-secret")
    monkeypatch.setenv("VOLCENGINE_VIDEO_POLL_SECONDS", "0")
    monkeypatch.setenv("VOLCENGINE_VIDEO_MODEL", "doubao-seedance-1-0-pro-fast-251015")
    monkeypatch.setenv("VOLCENGINE_VIDEO_GENERATE_AUDIO", "false")
    get_settings.cache_clear()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return VolcengineSeedanceProvider(client=client)


def test_seedance_provider_uses_requested_generation_settings(monkeypatch) -> None:
    requests: list[httpx.Request] = []
    status_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal status_calls
        requests.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["model"] == "doubao-seedance-1-0-pro-fast-251015"
            assert body["resolution"] == "720p"
            assert body["ratio"] == "16:9"
            assert body["duration"] == 5
            assert "generate_audio" not in body
            assert body["watermark"] is True
            assert "draft" not in body
            assert body["content"][0]["type"] == "text"
            assert "童年" in body["content"][0]["text"]
            return httpx.Response(200, json={"id": "task-1"})
        if request.url.host == "media.example":
            assert "authorization" not in request.headers
            return httpx.Response(
                200, content=b"seedance-video", headers={"content-type": "video/mp4"}
            )
        status_calls += 1
        if status_calls == 1:
            return httpx.Response(200, json={"id": "task-1", "status": "queued"})
        return httpx.Response(
            200,
            json={
                "id": "task-1",
                "status": "succeeded",
                "duration": 5,
                "content": {"video_url": "https://media.example/video.mp4"},
            },
        )

    provider = _seedance_provider(monkeypatch, handler)
    try:
        output = provider.render(
            "母亲的故事",
            [{"heading": "童年", "visual_prompt": "清晨的老街", "narration": "我在这里长大。"}],
        )
        assert output.content == b"seedance-video"
        assert output.mime_type == "video/mp4"
        assert output.parameters["provider_job_id"] == "task-1"
        assert output.parameters["resolution"] == "720p"
        assert output.parameters["ratio"] == "16:9"
        assert requests[0].headers["authorization"] == "Bearer test-provider-secret"
    finally:
        provider.client.close()
        from lifereel_api.core.config import get_settings

        get_settings.cache_clear()


def test_seedance_provider_requires_api_key(monkeypatch) -> None:
    from lifereel_api.core.config import get_settings
    from lifereel_api.modules.production.providers import (
        VideoProviderError,
        VolcengineSeedanceProvider,
    )

    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(VideoProviderError, match="VIDEO_PROVIDER_CONFIGURATION_INCOMPLETE"):
        VolcengineSeedanceProvider()
    get_settings.cache_clear()


def test_seedance_segment_sends_native_audio_and_previous_frame(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "doubao-seedance-2-0-mini-260615"
        assert body["duration"] == 15
        assert body["generate_audio"] is True
        assert body["resolution"] == "720p"
        assert body["ratio"] == "16:9"
        assert body["content"][1] == {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(b"frame").decode()},
            "role": "first_frame",
        }
        return httpx.Response(200, json={"id": "native-audio-task"})

    provider = _seedance_provider(monkeypatch, handler)
    provider.model = "doubao-seedance-2-0-mini-260615"
    provider.generate_audio = True
    try:
        assert provider.submit_segment("Narration", 15, b"frame") == "native-audio-task"
    finally:
        provider.client.close()
        from lifereel_api.core.config import get_settings

        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("status_payload", "expected_code"),
    [
        ({"status": "failed", "error": {"code": "ProviderFailure"}}, "VIDEO_PROVIDER_FAILED"),
        ({"status": "succeeded", "content": {}}, "VIDEO_PROVIDER_OUTPUT_INVALID"),
    ],
)
def test_seedance_provider_returns_stable_error_codes(
    monkeypatch, status_payload, expected_code
) -> None:
    from lifereel_api.modules.production.providers import VideoProviderError

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "task-error"})
        return httpx.Response(200, json={"id": "task-error", **status_payload})

    provider = _seedance_provider(monkeypatch, handler)
    try:
        with pytest.raises(VideoProviderError) as captured:
            provider.render("测试", [{"heading": "第一章"}])
        assert captured.value.code == expected_code
    finally:
        provider.client.close()
        from lifereel_api.core.config import get_settings

        get_settings.cache_clear()


def test_seedance_provider_times_out_with_error_code(monkeypatch) -> None:
    from lifereel_api.core.config import get_settings
    from lifereel_api.modules.production.providers import VideoProviderError

    monkeypatch.setenv("VOLCENGINE_VIDEO_TIMEOUT_SECONDS", "0")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "task-timeout"})
        return httpx.Response(200, json={"id": "task-timeout", "status": "running"})

    provider = _seedance_provider(monkeypatch, handler)
    try:
        with pytest.raises(VideoProviderError) as captured:
            provider.render("测试", [{"heading": "第一章"}])
        assert captured.value.code == "VIDEO_PROVIDER_TIMEOUT"
    finally:
        provider.client.close()
        get_settings.cache_clear()


def test_seedance_provider_maps_unavailable_model_to_configuration_error(monkeypatch) -> None:
    from lifereel_api.modules.production.providers import VideoProviderError

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "error": {
                    "code": "InvalidEndpointOrModel.NotFound",
                    "message": "not exposed to the application user",
                }
            },
        )

    provider = _seedance_provider(monkeypatch, handler)
    try:
        with pytest.raises(VideoProviderError) as captured:
            provider.render("测试", [{"heading": "第一章"}])
        assert captured.value.code == "VIDEO_PROVIDER_CONFIGURATION_INCOMPLETE"
        assert captured.value.provider_error_code == "InvalidEndpointOrModel.NotFound"
    finally:
        provider.client.close()
        from lifereel_api.core.config import get_settings

        get_settings.cache_clear()

import base64
import json
from io import BytesIO
from uuid import UUID

import httpx
import pytest
from PIL import Image
from test_photo_restoration import BASE, RESTORED, execute, restoration, start, upload

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.restoration import service
from lifereel_api.providers import seedream, siliconflow

__all__ = ["restoration"]


def image_bytes(width=160, height=90, orientation=None):
    output = BytesIO()
    image = Image.new("RGB", (width, height), "gray")
    exif = Image.Exif()
    if orientation:
        exif[274] = orientation
    image.save(output, format="PNG", exif=exif)
    return output.getvalue()


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "photo_restoration_provider", "seedream")
    monkeypatch.setattr(get_settings(), "volcengine_api_key", "test-only-seedream")
    monkeypatch.setattr(
        siliconflow.socket, "getaddrinfo", lambda *_a, **_kw: [(2, 1, 6, "", ("8.8.8.8", 443))]
    )


@pytest.mark.parametrize(
    "width,height,orientation,expected",
    [(160, 90, None, "1920x1080"), (90, 160, None, "1080x1920"),
     (160, 90, 6, "1080x1920"), (100, 100, None, "1440x1440"),
     (1600, 100, None, "5760x360"), (100, 1600, None, "360x5760")],
)
def test_1080p_preserves_ratio_and_orientation(width, height, orientation, expected):
    assert seedream.output_size(image_bytes(width, height, orientation)) == expected


@pytest.mark.parametrize("content", [b"broken", image_bytes(10, 30), image_bytes(1700, 100)])
def test_invalid_source_is_rejected_before_request(content):
    with pytest.raises(ApiError) as raised:
        seedream.output_size(content)
    assert raised.value.code == ErrorCode.PHOTO_RESTORATION_SOURCE_INVALID


def test_exact_request_defaults_one_image_and_download_without_credentials(configured):
    source = image_bytes()
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            assert str(request.url).endswith("/api/v3/images/generations")
            assert request.headers["authorization"] == "Bearer test-only-seedream"
            assert json.loads(request.content) == {
                "model": seedream.MODEL, "size": "1920x1080", "prompt": service.prompt(False),
                "image": "data:image/png;base64," + base64.b64encode(source).decode(),
            }
            return httpx.Response(200, headers={"x-request-id": "seedream-test"}, json={
                "data": [{"url": "https://example.org/output.jpg"}],
            })
        assert "authorization" not in request.headers
        if request.url.path == "/output.jpg":
            return httpx.Response(302, headers={"location": "https://example.org/final.jpg"})
        return httpx.Response(200, content=b"\xff\xd8\xffsynthetic-jpeg")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = seedream.edit(
            source, "image/png", prompt=service.prompt(False), size="1920x1080", client=client,
        )
    assert result.mime_type == "image/jpeg" and result.trace_id == "seedream-test"
    assert len(calls) == 3


@pytest.mark.parametrize("case,code", [
    ("reject", "PHOTO_RESTORATION_REJECTED"),
    ("embedded_reject", "PHOTO_RESTORATION_REJECTED"),
    ("timeout", "PHOTO_RESTORATION_UNCERTAIN"),
    ("server", "PHOTO_RESTORATION_FAILED"),
    ("multiple", "PHOTO_RESTORATION_RESULT_INVALID"),
    ("private_redirect", "PHOTO_RESTORATION_RESULT_INVALID"),
    ("oversized", "PHOTO_RESTORATION_RESULT_INVALID"),
    ("invalid_image", "PHOTO_RESTORATION_RESULT_INVALID"),
])
def test_provider_failures_do_not_retry(configured, monkeypatch, case, code):
    posts = []

    def handler(request):
        if request.method == "POST":
            posts.append(request)
            if case == "reject":
                return httpx.Response(400, json={"error": "sensitive provider message"})
            if case == "server":
                return httpx.Response(500)
            if case == "timeout":
                raise httpx.ReadTimeout("sensitive provider message")
            data = [{"url": "https://example.org/output.jpg"}]
            if case == "multiple":
                data *= 2
            if case == "embedded_reject":
                data = [{"error": {"code": "OutputImageSensitiveContentDetected"}}]
            return httpx.Response(200, json={"data": data})
        if case == "private_redirect":
            monkeypatch.setattr(siliconflow.socket, "getaddrinfo", lambda *_a, **_kw: [
                (2, 1, 6, "", ("127.0.0.1", 443)),
            ])
            return httpx.Response(302, headers={"location": "https://localhost/private"})
        if case == "oversized":
            return httpx.Response(200, content=b"x" * (siliconflow.MAX_BYTES + 1))
        return httpx.Response(200, content=b"not an image")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ApiError) as raised:
            seedream.edit(image_bytes(), "image/png", prompt="restore", size="1920x1080",
                          client=client)
    assert raised.value.code.value == code
    assert "sensitive provider message" not in str(raised.value)
    assert len(posts) == 1


def test_switch_separates_jobs_preserves_old_provider_and_freezes_new_parameters(
    client, restoration, configured, monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "photo_restoration_provider", "inherit")
    photo = upload(client, image_bytes())
    old = start(client, photo)
    monkeypatch.setattr(settings, "photo_restoration_provider", "seedream")
    calls = []

    def edit(content, mime, *, prompt, size):
        calls.append(size)
        return siliconflow.RedrawOutput(RESTORED, "image/png")

    monkeypatch.setattr(seedream, "edit", edit)
    new = start(client, photo)
    assert new["id"] != old["id"]
    assert start(client, photo)["id"] == new["id"]
    with SessionLocal() as db:
        payload = db.get(Job, UUID(new["id"])).payload
        assert payload["model"] == seedream.MODEL
        assert payload["size"] == "1920x1080" and payload["image_count"] == 1
        assert payload["provider"] == "seedream"
    assert execute()["status"] == "completed"
    assert len(restoration) == 1 and calls == []
    # Standalone restoration must not depend on the video portrait provider.
    monkeypatch.setattr(settings, "photo_redraw_provider", "disabled")
    assert client.get(f"{BASE}/settings").json()["enabled"] is True
    assert execute()["status"] == "completed"
    assert calls == ["1920x1080"]
    monkeypatch.setattr(settings, "volcengine_api_key", None)
    assert client.get(f"{BASE}/settings").json()["enabled"] is False

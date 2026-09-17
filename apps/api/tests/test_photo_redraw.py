import base64
import hashlib
import json
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.evidence import redraw
from lifereel_api.modules.evidence.models import SourceAsset
from lifereel_api.modules.evidence.storage import private_storage
from lifereel_api.modules.jobs.dispatch import claim_job, execute_claim
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.production.references import build_reference_package
from lifereel_api.providers import siliconflow

SOURCE = b"\x89PNG\r\n\x1a\nsynthetic-source"
OUTPUT = b"\x89PNG\r\n\x1a\nsynthetic-output"


@pytest.fixture
def photo(client, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "local_storage_path", str(tmp_path))
    monkeypatch.setattr(get_settings(), "photo_redraw_provider", "mock")
    monkeypatch.setattr(get_settings(), "job_queue_backend", "database")
    person = client.post("/v1/persons", json={"display_name": "Synthetic subject"}).json()
    response = client.post(
        "/v1/evidence/assets", data={"subject_id": person["id"], "kind": "photo"},
        files={"file": ("original.png", SOURCE, "image/png")},
    )
    assert response.status_code == 201
    return response.json()


def enqueue(client, photo):
    response = client.post(f"/v1/evidence/assets/{photo['id']}/redraw")
    assert response.status_code == 202, response.text
    return response.json()


def execute_one():
    with SessionLocal() as db:
        claim = claim_job(db, "video")
        assert claim
        return execute_claim(db, UUID(claim["job_id"]), UUID(claim["token"]))


def test_redraw_job_preserves_source_and_privately_saves_traceable_result(
    client, photo, monkeypatch,
):
    calls = []

    def fake(content, mime):
        calls.append((content, mime))
        return siliconflow.RedrawOutput(OUTPUT, "image/png", "trace-test")

    monkeypatch.setattr(siliconflow, "redraw", fake)
    job = enqueue(client, photo)
    assert enqueue(client, photo)["id"] == job["id"]
    assert execute_one() == {"status": "completed"}
    result = client.get(f"/v1/evidence/assets/{photo['id']}/redraw").json()["job"]
    assert result["attempt_count"] == 1
    assert enqueue(client, photo)["id"] == job["id"]
    assert calls == [(SOURCE, "image/png")]
    derived_id = result["result"]["asset_id"]
    assets = client.get(f"/v1/evidence/assets?subject_id={photo['subject_id']}").json()
    derived = next(asset for asset in assets if asset["id"] == derived_id)
    assert derived["is_redraw"] and derived["derived_from_asset_id"] == photo["id"]
    assert client.get(f"/v1/evidence/assets/{photo['id']}/content").content == SOURCE
    assert client.get(f"/v1/evidence/assets/{derived_id}/content").content == OUTPUT
    assert client.post(f"/v1/evidence/assets/{derived_id}/redraw").status_code == 422
    assert client.post(f"/v1/evidence/assets/{derived_id}/analyze").status_code == 422
    with SessionLocal() as db:
        output = db.get(SourceAsset, UUID(derived_id))
        assert output.sha256 == hashlib.sha256(OUTPUT).hexdigest()
        assert output.metadata_json["prompt"] == siliconflow.PROMPT
        assert output.metadata_json["video_reference_approved"] is False
        package = build_reference_package(db, output.tenant_id, output.subject_id, None)
        assert package["character_reference"] == photo["id"]
        assert derived_id not in package["source_assets"]
        # Repeat delivery of completed work never contacts the provider.
        redraw.execute(db, db.get(Job, UUID(job["id"])))
    assert len(calls) == 1


@pytest.mark.parametrize("change", [
    {"consent_status": "revoked"}, {"status": "processing"}, {"kind": "video"},
    {"mime_type": "image/svg+xml"}, {"byte_size": siliconflow.MAX_BYTES + 1},
    {"derived_from_asset_id": uuid4()},
])
def test_invalid_sources_never_queue(client, photo, change):
    with SessionLocal() as db:
        source = db.get(SourceAsset, UUID(photo["id"]))
        for key, value in change.items():
            setattr(source, key, value)
        db.commit()
    assert client.post(f"/v1/evidence/assets/{photo['id']}/redraw").status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(Job.id)) is None


def test_source_is_rechecked_and_tenant_scoped(client, photo, monkeypatch):
    job = enqueue(client, photo)
    monkeypatch.setattr(siliconflow, "redraw", lambda *_: pytest.fail("AI must not be called"))
    with SessionLocal() as db:
        source = db.get(SourceAsset, UUID(photo["id"]))
        source.tenant_id = uuid4()
        db.commit()
    assert client.get(f"/v1/evidence/assets/{photo['id']}/redraw").status_code == 404
    assert execute_one() == {"status": "failed"}
    assert client.get(f"/v1/jobs/{job['id']}").json()["error_code"] == "EVIDENCE_ASSET_NOT_FOUND"


def test_changed_source_bytes_fail_without_ai_call(client, photo, monkeypatch):
    enqueue(client, photo)
    with SessionLocal() as db:
        source = db.get(SourceAsset, UUID(photo["id"]))
        private_storage().root.joinpath(source.storage_key).write_bytes(b"changed")
    monkeypatch.setattr(siliconflow, "redraw", lambda *_: pytest.fail("AI must not be called"))
    assert execute_one() == {"status": "failed"}


def test_revoked_consent_during_call_prevents_publishing_result(client, photo, monkeypatch):
    enqueue(client, photo)

    def revoke(*_):
        with SessionLocal() as db:
            db.get(SourceAsset, UUID(photo["id"])).consent_status = "revoked"
            db.commit()
        return siliconflow.RedrawOutput(OUTPUT, "image/png")

    monkeypatch.setattr(siliconflow, "redraw", revoke)
    assert execute_one() == {"status": "failed"}
    assert len(client.get(f"/v1/evidence/assets?subject_id={photo['subject_id']}").json()) == 1


def test_interrupted_submission_is_not_automatically_repeated(client, photo, monkeypatch):
    job = enqueue(client, photo)
    with SessionLocal() as db:
        row = db.get(Job, UUID(job["id"]))
        row.status = "running"
        row.attempt_count = 1
        row.result = {"request_started": True}
        db.commit()
    monkeypatch.setattr(siliconflow, "redraw", lambda *_: pytest.fail("AI must not be repeated"))
    assert execute_one() == {"status": "failed"}
    row = client.get(f"/v1/jobs/{job['id']}").json()
    assert row["error_code"] == "PHOTO_REDRAW_UNCERTAIN"
    assert client.post(f"/v1/jobs/{job['id']}/retry").status_code == 200
    assert client.get(f"/v1/jobs/{job['id']}").json()["result"] is None


@pytest.mark.parametrize("code,attempts,expected", [
    ("PHOTO_REDRAW_FAILED", 1, 200), ("PHOTO_REDRAW_FAILED", 3, 409),
    ("PHOTO_REDRAW_REJECTED", 1, 409),
])
def test_explicit_retry_limits(client, photo, code, attempts, expected):
    job = enqueue(client, photo)
    with SessionLocal() as db:
        row = db.get(Job, UUID(job["id"]))
        row.status, row.error_code, row.attempt_count = "failed", code, attempts
        db.commit()
    assert client.post(f"/v1/jobs/{job['id']}/retry").status_code == expected


def test_configuration_and_mock_are_fail_closed(client, photo, monkeypatch):
    monkeypatch.setattr(get_settings(), "photo_redraw_provider", "disabled")
    assert client.get(f"/v1/evidence/assets/{photo['id']}/redraw").json()["enabled"] is False
    assert client.post(f"/v1/evidence/assets/{photo['id']}/redraw").status_code == 503
    monkeypatch.setattr(get_settings(), "photo_redraw_provider", "mock")
    monkeypatch.setattr(get_settings(), "app_env", "production")
    with pytest.raises(ApiError, match="PHOTO_REDRAW_NOT_CONFIGURED"):
        siliconflow.redraw(SOURCE, "image/png")


def provider_client(monkeypatch, handler):
    monkeypatch.setattr(get_settings(), "photo_redraw_provider", "siliconflow")
    monkeypatch.setattr(get_settings(), "siliconflow_api_key", "test-only-secret")
    monkeypatch.setattr(siliconflow.socket, "getaddrinfo", lambda *_a, **_kw: [
        (2, 1, 6, "", ("8.8.8.8", 443)),
    ])
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_provider_uses_exact_prompt_and_downloads_without_credentials(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["model"] == "Qwen/Qwen-Image-Edit-2509"
            assert payload["prompt"] == siliconflow.PROMPT
            assert "右下角" in payload["prompt"] and "本图片由ai生成" in payload["prompt"]
            assert "转描" not in payload["prompt"] and "手绘" not in payload["prompt"]
            assert payload["num_inference_steps"] == 20
            assert "image_size" not in payload and "guidance_scale" not in payload
            assert payload["image"] == "data:image/png;base64," + base64.b64encode(SOURCE).decode()
            assert request.headers["X-Enable-Watermark"] == "1"
            return httpx.Response(200, json={"images": [{"url": "https://media.example/image"}]})
        assert "Authorization" not in request.headers
        return httpx.Response(200, content=OUTPUT)

    with provider_client(monkeypatch, handler) as client:
        assert siliconflow.redraw(SOURCE, "image/png", client=client).content == OUTPUT
    assert len(calls) == 2


@pytest.mark.parametrize("mode,code", [
    ("timeout", ErrorCode.PHOTO_REDRAW_UNCERTAIN),
    ("rejected", ErrorCode.PHOTO_REDRAW_REJECTED),
    ("bad_image", ErrorCode.PHOTO_REDRAW_RESULT_INVALID),
    ("private_redirect", ErrorCode.PHOTO_REDRAW_RESULT_INVALID),
    ("oversize", ErrorCode.PHOTO_REDRAW_RESULT_INVALID),
])
def test_provider_failure_handling(monkeypatch, mode, code):
    def handler(request):
        if request.method == "POST":
            if mode == "timeout":
                raise httpx.ReadTimeout("synthetic timeout")
            if mode == "rejected":
                return httpx.Response(400, json={"message": "not persisted"})
            return httpx.Response(200, json={"images": [{"url": "https://media.example/image"}]})
        if mode == "private_redirect":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        return httpx.Response(200, content=b"<html>" if mode == "bad_image" else b"x" * 100)

    monkeypatch.setattr(siliconflow, "MAX_BYTES", 50)
    with provider_client(monkeypatch, handler) as client, pytest.raises(ApiError) as exc:
        siliconflow.redraw(SOURCE, "image/png", client=client)
    assert exc.value.code == code


def test_download_url_rejects_private_dns(monkeypatch):
    monkeypatch.setattr(siliconflow.socket, "getaddrinfo", lambda *_a, **_kw: [
        (2, 1, 6, "", ("127.0.0.1", 443)),
    ])
    with pytest.raises(ValueError):
        siliconflow.validate_download_url("https://media.example/image")

import base64
import json
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.jobs.dispatch import claim_job, execute_claim
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.production.references import build_reference_package
from lifereel_api.modules.restoration import service
from lifereel_api.modules.restoration.models import RestorationPhoto
from lifereel_api.providers import siliconflow

BASE = "/v1/photo-restoration"
SOURCE = b"\x89PNG\r\n\x1a\nsynthetic-old-photo"
RESTORED = b"\x89PNG\r\n\x1a\nsynthetic-restored-photo"


@pytest.fixture
def restoration(client, monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "photo_redraw_provider", "mock")
    monkeypatch.setattr(settings, "job_queue_backend", "database")
    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path))
    calls = []

    def edit(content, mime, *, prompt):
        calls.append((content, mime, prompt))
        return siliconflow.RedrawOutput(RESTORED, "image/png", "restoration-test")

    monkeypatch.setattr(siliconflow, "edit", edit)
    return calls


def upload(client, content=SOURCE):
    response = client.post(f"{BASE}/photos", files={"file": ("old.png", content, "image/png")})
    assert response.status_code == 201, response.text
    return response.json()


def start(client, photo, **options):
    response = client.post(f"{BASE}/runs", json={"photo_id": photo["id"], **options})
    assert response.status_code == 202, response.text
    return response.json()


def execute():
    with SessionLocal() as db:
        claim = claim_job(db, "video")
        assert claim
        return execute_claim(db, UUID(claim["job_id"]), UUID(claim["token"]))


def test_standalone_upload_is_private_and_only_explicit_start_calls_provider(client, restoration):
    photo = upload(client)
    assert "subject_id" not in photo and "storage_key" not in photo
    assert upload(client)["id"] == photo["id"]
    assert client.get(f"{BASE}/runs").json()["total"] == 0
    assert restoration == []
    run = start(client, photo)
    assert run["colorize"] is False and run["status"] == "queued"
    assert start(client, photo)["id"] == run["id"]
    assert execute() == {"status": "completed"}
    assert len(restoration) == 1
    assert "黑白照片保持黑白" in restoration[0][2]
    assert "不转为插画或卡通" in restoration[0][2]
    assert client.get(f"{BASE}/photos/{photo['id']}/content").content == SOURCE
    download = client.get(f"{BASE}/runs/{run['id']}/content?download=true")
    assert download.content == RESTORED
    assert download.headers["content-disposition"].startswith("attachment;")
    assert client.get(f"{BASE}/runs").json()["items"][0]["status"] == "completed"
    with SessionLocal() as db:
        service.execute(db, db.get(Job, UUID(run["id"])))
    assert len(restoration) == 1


def test_color_and_prompt_version_have_separate_jobs_and_frozen_input(
    client, restoration, monkeypatch
):
    photo = upload(client)
    normal = start(client, photo)
    colored = start(client, photo, colorize=True)
    assert colored["id"] != normal["id"]
    assert execute()["status"] == "completed"
    assert execute()["status"] == "completed"
    assert "添加自然克制的色彩" in restoration[-1][2]
    monkeypatch.setattr(service, "PROMPT_VERSION", "photo-restoration-next")
    later = start(client, photo)
    assert later["id"] not in {normal["id"], colored["id"]}
    assert client.get(f"{BASE}/runs").json()["total"] == 3


def test_other_tenant_cannot_read_start_save_or_retry(client, restoration):
    photo = upload(client)
    run = start(client, photo)
    person = client.post("/v1/persons", json={"display_name": "Restore test"}).json()
    headers = {"X-Tenant-ID": str(uuid4())}
    for url in (
        f"{BASE}/photos/{photo['id']}/content",
        f"{BASE}/runs/{run['id']}",
        f"{BASE}/runs/{run['id']}/content",
    ):
        assert client.get(url, headers=headers).status_code == 404
    assert (
        client.post(f"{BASE}/runs", json={"photo_id": photo["id"]}, headers=headers).status_code
        == 404
    )
    assert (
        client.post(
            f"{BASE}/runs/{run['id']}/save", json={"subject_id": person["id"]}, headers=headers
        ).status_code
        == 404
    )
    assert client.post(f"/v1/jobs/{run['id']}/retry", headers=headers).status_code == 404
    assert client.get(f"{BASE}/runs", headers=headers).json()["total"] == 0
    assert restoration == []


@pytest.mark.parametrize(
    "content",
    [b"", b"not-an-image", SOURCE + b"0" * siliconflow.MAX_BYTES],
    ids=["empty", "invalid", "oversized"],
)
def test_invalid_upload_does_not_create_job(client, restoration, content):
    response = client.post(f"{BASE}/photos", files={"file": ("bad.png", content, "image/png")})
    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(Job.id)) is None
        assert db.scalar(select(RestorationPhoto.id)) is None


def test_disabled_provider_blocks_paid_work(client, restoration, monkeypatch):
    photo = upload(client)
    monkeypatch.setattr(get_settings(), "photo_redraw_provider", "disabled")
    assert client.get(f"{BASE}/settings").json()["enabled"] is False
    assert client.post(f"{BASE}/runs", json={"photo_id": photo["id"]}).status_code == 503
    assert restoration == []


@pytest.mark.parametrize(
    "code,retry_status",
    [
        (ErrorCode.PHOTO_REDRAW_FAILED, 200),
        (ErrorCode.PHOTO_REDRAW_UNCERTAIN, 200),
        (ErrorCode.PHOTO_REDRAW_REJECTED, 409),
    ],
)
def test_failed_work_is_not_automatically_repeated(
    client, restoration, monkeypatch, code, retry_status
):
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise ApiError(502, code)

    monkeypatch.setattr(siliconflow, "edit", fail)
    run = start(client, upload(client))
    assert client.get(f"{BASE}/runs/{run['id']}/content").status_code == 409
    assert execute()["status"] == "failed"
    detail = client.get(f"{BASE}/runs/{run['id']}").json()
    assert detail["error_code"] == code.value.replace("PHOTO_REDRAW_", "PHOTO_RESTORATION_")
    with SessionLocal() as db:
        assert claim_job(db, "video") is None
    assert client.post(f"/v1/jobs/{run['id']}/retry").status_code == retry_status
    if retry_status == 200:
        monkeypatch.setattr(
            siliconflow, "edit", lambda *_a, **_kw: siliconflow.RedrawOutput(RESTORED, "image/png")
        )
        assert execute()["status"] == "completed"
    assert len(calls) == 1


def test_interrupted_paid_request_stays_uncertain(client, restoration):
    run = start(client, upload(client))
    with SessionLocal() as db:
        job = db.get(Job, UUID(run["id"]))
        job.status = "running"
        job.attempt_count = 1
        job.result = {"request_started": True}
        db.commit()
    assert execute()["status"] == "failed"
    assert restoration == []
    assert (
        client.get(f"{BASE}/runs/{run['id']}").json()["error_code"] == "PHOTO_RESTORATION_UNCERTAIN"
    )


def test_save_is_explicit_idempotent_and_does_not_turn_repairs_into_evidence(client, restoration):
    photo = upload(client)
    run = start(client, photo)
    person = client.post("/v1/persons", json={"display_name": "Photo owner"}).json()
    assert execute()["status"] == "completed"
    assert client.get(f"/v1/evidence/assets?subject_id={person['id']}").json() == []
    url = f"{BASE}/runs/{run['id']}/save"
    asset = client.post(url, json={"subject_id": person["id"]}).json()
    assert asset["is_restoration"] is True and asset["is_redraw"] is False
    assert client.post(url, json={"subject_id": person["id"]}).json()["id"] == asset["id"]
    assert client.get(f"/v1/evidence/assets/{asset['id']}/content").content == RESTORED
    assert client.post(f"/v1/evidence/assets/{asset['id']}/analyze").status_code == 422
    assert client.post(url, json={"subject_id": str(uuid4())}).status_code == 404
    with SessionLocal() as db:
        package = build_reference_package(db, UUID(person["tenant_id"]), UUID(person["id"]), None)
        assert package["source_assets"] == []


def test_restoration_uses_image_edit_http_with_its_own_prompt(monkeypatch):
    monkeypatch.setattr(get_settings(), "photo_redraw_provider", "siliconflow")
    monkeypatch.setattr(get_settings(), "siliconflow_api_key", "test-only")
    monkeypatch.setattr(
        siliconflow.socket, "getaddrinfo", lambda *_a, **_kw: [(2, 1, 6, "", ("8.8.8.8", 443))]
    )

    def handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["model"] == "Qwen/Qwen-Image-Edit-2509"
            assert body["prompt"] == service.prompt(False) != siliconflow.PROMPT
            assert base64.b64decode(body["image"].split(",", 1)[1]) == SOURCE
            return httpx.Response(
                200, json={"images": [{"url": "https://example.org/restored.png"}]}
            )
        return httpx.Response(200, content=RESTORED)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = siliconflow.edit(SOURCE, "image/png", prompt=service.prompt(False), client=client)
    assert result.content == RESTORED

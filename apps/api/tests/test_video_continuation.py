import copy
import hashlib
import json
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from test_video_recovery import blocked_run as blocked_run

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.billing.models import Wallet
from lifereel_api.modules.evidence.storage import LocalPrivateStorage
from lifereel_api.modules.production import continuation, segmented
from lifereel_api.modules.production.models import ProductionRun
from lifereel_api.modules.production.providers import VideoProviderError, VolcengineSeedanceProvider

MODEL = "doubao-seedance-2-0-mini-260615"


@pytest.fixture
def originals(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "volcengine_api_key", "test-key")
    monkeypatch.setattr(get_settings(), "local_storage_path", str(tmp_path))
    requests = []
    result = {
        "id": "task-1",
        "model": MODEL,
        "status": "succeeded",
        "created_at": int(time.time()),
        "usage": {"completion_tokens": 12},
        "content": {
            "video_url": "https://provider.test/video",
            "last_frame_url": "https://provider.test/tail",
        },
    }

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "task-2"})
        if request.url.path.endswith("/video"):
            return httpx.Response(
                200, content=b"original-video", headers={"content-type": "video/mp4"}
            )
        if request.url.path.endswith("/tail"):
            return httpx.Response(
                200, content=b"original-tail", headers={"content-type": "image/png"}
            )
        return httpx.Response(200, json=result)

    provider = VolcengineSeedanceProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    provider.model = MODEL
    run = SimpleNamespace(tenant_id=uuid4(), id=uuid4())
    storage = LocalPrivateStorage()
    segment = {
        "status": "completed",
        "task_id": "task-1",
        "storage_key": continuation.segment_key(run, 0),
    }
    storage.put(segment["storage_key"], b"original-video")
    yield provider, storage, run, segment, requests, result
    provider.client.close()


def test_downloads_official_tail_without_reencoding_and_submits_identical_bytes(originals):
    provider, storage, run, segment, requests, _ = originals
    output = provider.fetch_segment("task-1", 15)
    assert output.last_frame == b"original-tail"
    assert output.parameters["last_frame_mime"] == "image/png"
    segment["parameters"] = output.parameters
    continuation.save_tail(storage, run, 0, segment, output.last_frame, "image/png")
    frame, options, source = continuation.prepare_original(provider, storage, run, 0, segment)
    assert frame == b"original-tail"
    assert source["kind"] == "official_tail"
    assert len(requests) == 3
    provider.submit_segment("continue", 15, frame, **options)
    body = json.loads(requests[-1].content)
    assert body["return_last_frame"] is True
    assert body["content"][1] == {
        "type": "image_url",
        "role": "first_frame",
        "image_url": {"url": "data:image/png;base64,b3JpZ2luYWwtdGFpbA=="},
    }
    assert "https://" not in json.dumps(segment)


def test_legacy_task_retrieves_official_tail_if_available(originals):
    provider, storage, run, segment, _, _ = originals
    frame, options, source = continuation.prepare_original(provider, storage, run, 0, segment)
    assert frame == b"original-tail"
    assert options == {"reference_mime": "image/png"}
    assert source["source_task_id"] == "task-1"
    assert storage.get(segment["official_tail"]["storage_key"]) == frame


def test_legacy_without_tail_uses_unmodified_video_and_no_image(originals):
    provider, storage, run, segment, requests, result = originals
    result["content"].pop("last_frame_url")
    frame, options, source = continuation.prepare_original(provider, storage, run, 0, segment)
    assert frame is None and source["kind"] == "original_video"
    provider.submit_segment("extend", 15, frame, **options)
    body = json.loads(requests[-1].content)
    assert body["content"][1] == {
        "type": "video_url",
        "role": "reference_video",
        "video_url": {"url": "https://provider.test/video"},
    }
    assert "image_url" not in json.dumps(body)
    assert "https://" not in json.dumps(segment)


@pytest.mark.parametrize(
    "change", ["expired", "different_task", "different_file", "different_tenant"]
)
def test_untrusted_original_is_rejected_before_submission(originals, change):
    provider, storage, run, segment, requests, result = originals
    if change == "expired":
        result["created_at"] -= continuation.TRUST_SECONDS + 1
    elif change == "different_task":
        result["id"] = "another-task"
    elif change == "different_file":
        storage.root.joinpath(segment["storage_key"]).write_bytes(b"edited")
    else:
        run.tenant_id = uuid4()
    with pytest.raises(VideoProviderError, match="VIDEO_CONTINUATION_UNAVAILABLE"):
        continuation.prepare_original(provider, storage, run, 0, segment)
    assert not any(request.method == "POST" for request in requests)


def test_tampered_saved_tail_is_rejected(originals):
    provider, storage, run, segment, _, _ = originals
    continuation.prepare_original(provider, storage, run, 0, segment)
    storage.root.joinpath(segment["official_tail"]["storage_key"]).write_bytes(b"resized")
    with pytest.raises(VideoProviderError, match="VIDEO_CONTINUATION_UNAVAILABLE"):
        continuation.prepare_original(provider, storage, run, 0, segment)


def legacy_run(client, blocked_run):
    run, submissions = blocked_run
    with SessionLocal() as db:
        row = db.get(ProductionRun, UUID(run["id"]))
        manifest = copy.deepcopy(row.output_manifest)
        manifest["segments"][1].pop("reference_kind", None)
        row.output_manifest = manifest
        db.commit()
    return client.get("/v1/production/runs").json()[0], submissions


def test_original_recovery_preserves_first_clip_and_bills_only_new_segment(
    client, monkeypatch, blocked_run
):
    run, submissions = legacy_run(client, blocked_run)
    assert run["recovery"]["can_restore_original"] is True
    before = copy.deepcopy(run["output_manifest"]["segments"][0])
    source = {
        "kind": "original_video",
        "sha256": hashlib.sha256(b"clip").hexdigest(),
        "source_task_id": "task-1",
    }

    def prepare(*args):
        return None, {"reference_video_url": "https://provider.test/video"}, source

    monkeypatch.setattr(continuation, "prepare_original", prepare)
    monkeypatch.setattr(segmented, "prepare_original", prepare)
    url = f"/v1/production/runs/{run['id']}"
    assert (
        client.post(url + "/continuation", headers={"X-Tenant-ID": str(uuid4())}).status_code == 404
    )
    response = client.post(url + "/continuation")
    assert response.status_code == 200, response.text
    assert response.json()["output_manifest"]["segments"][0] == before
    assert client.post(url + "/continuation").status_code == 409
    assert client.post(url + "/execute").json()["status"] == "running"
    done = client.post(url + "/execute").json()
    assert done["status"] == "completed"
    assert len(submissions) == 3
    assert submissions[-1] == (None, {"reference_video_url": "https://provider.test/video"})
    assert done["output_manifest"]["billing"]["charged_cents"] == 1803
    balance = client.get("/v1/wallet").json()
    assert balance["frozen_cents"] == 0
    client.post(url + "/execute")
    assert client.get("/v1/wallet").json() == balance


@pytest.mark.parametrize("failure", ["invalid_source", "no_balance"])
def test_recovery_failure_does_not_change_wallet_or_run(client, monkeypatch, blocked_run, failure):
    run, _ = legacy_run(client, blocked_run)

    def prepare(*args):
        if failure == "invalid_source":
            raise VideoProviderError("VIDEO_CONTINUATION_UNAVAILABLE")
        return None, {}, {"kind": "original_video", "sha256": "hash", "source_task_id": "task-1"}

    monkeypatch.setattr(continuation, "prepare_original", prepare)
    if failure == "no_balance":
        with SessionLocal() as db:
            db.get(Wallet, get_settings().default_tenant_id).bonus_cents = 0
            db.commit()
    wallet = client.get("/v1/wallet").json()
    result = client.post(f"/v1/production/runs/{run['id']}/continuation")
    assert result.status_code in {409, 422}
    assert client.get("/v1/wallet").json() == wallet
    assert client.get("/v1/production/runs").json()[0] == run


def test_rejected_original_cannot_be_restored_again(client, monkeypatch, blocked_run):
    run, _ = legacy_run(client, blocked_run)
    source = {"kind": "original_video", "sha256": "hash", "source_task_id": "task-1"}
    monkeypatch.setattr(continuation, "prepare_original", lambda *args: (None, {}, source))
    monkeypatch.setattr(segmented, "prepare_original", lambda *args: (None, {}, source))
    url = f"/v1/production/runs/{run['id']}"
    assert client.post(url + "/continuation").status_code == 200

    def reject(*args, **kwargs):
        raise VideoProviderError(
            "VIDEO_REFERENCE_REJECTED",
            provider_status="rejected",
            provider_error_code="InputVideoSensitiveContentDetected.PrivacyInformation",
        )

    monkeypatch.setattr(segmented.VolcengineSeedanceProvider, "submit_segment", reject)
    failed = client.post(url + "/execute").json()
    assert failed["status"] == "failed"
    assert failed["recovery"]["can_restore_original"] is False
    balance = client.get("/v1/wallet").json()
    assert client.post(url + "/continuation").status_code == 409
    assert client.post(f"/v1/jobs/{run['job_id']}/retry").status_code == 409
    assert client.get("/v1/wallet").json() == balance


@pytest.mark.parametrize("has_video,rate", [(False, 23), (True, 14)])
def test_video_input_uses_its_own_standard_token_price(has_video, rate):
    from lifereel_api.modules.billing.video import quote

    price = quote(
        MODEL, {"completion_tokens": 650000, "has_reference_video": has_video}, "succeeded"
    )
    assert price["official_cost_nano"] == 650000 * rate * 1000
    assert price["retail_nano"] == price["official_cost_nano"] * 3 // 2


def test_rotated_credentials_require_fresh_ownership_validation(originals):
    provider, storage, run, segment, requests, _ = originals
    continuation.prepare_original(provider, storage, run, 0, segment)
    before = len(requests)
    provider.headers["Authorization"] = "Bearer rotated-key"
    continuation.prepare_original(provider, storage, run, 0, segment)
    assert len(requests) == before + 3
    assert segment["parameters"]["original"]["scope"] == provider.source_scope

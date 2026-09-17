import copy
import hashlib
from uuid import UUID, uuid4

import httpx
import pytest
from test_segmented_production import setup_pipeline

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.billing.models import Wallet
from lifereel_api.modules.billing.usage import record
from lifereel_api.modules.evidence.models import SourceAsset
from lifereel_api.modules.evidence.storage import private_storage
from lifereel_api.modules.production import segmented
from lifereel_api.modules.production.models import ProductionRun
from lifereel_api.modules.production.providers import (
    ProviderOutput,
    VideoProviderError,
    VolcengineSeedanceProvider,
)
from lifereel_api.modules.script.models import ScriptProject

MODEL = "doubao-seedance-2-0-mini-260615"
REJECTION = "InputImageSensitiveContentDetected.PrivacyInformation"


@pytest.mark.parametrize(
    "provider_code,expected",
    [
        (REJECTION, "VIDEO_REFERENCE_REJECTED"),
        ("InputTextSensitiveContentDetected", "VIDEO_CONTENT_REJECTED"),
        ("OutputVideoSensitiveContentDetected", "VIDEO_CONTENT_REJECTED"),
        ("InternalError", "VIDEO_PROVIDER_REQUEST_FAILED"),
    ],
)
def test_provider_preserves_moderation_category(monkeypatch, provider_code, expected):
    monkeypatch.setattr(get_settings(), "volcengine_api_key", "synthetic")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                400,
                json={"error": {"code": provider_code, "message": "not for display"}},
            )
        )
    )
    provider = VolcengineSeedanceProvider(client=client)
    with pytest.raises(VideoProviderError) as error:
        provider.submit_segment("test", 15, b"frame")
    assert error.value.code == expected
    assert error.value.provider_error_code == provider_code
    assert error.value.provider_status == "rejected"
    client.close()


@pytest.fixture
def blocked_run(client, monkeypatch):
    payload = setup_pipeline(client, monkeypatch)
    monkeypatch.setattr(get_settings(), "billing_video_mode", "tokens")
    monkeypatch.setattr(get_settings(), "volcengine_video_resolution", "720p")
    submissions = []

    class Provider:
        def __init__(self, options):
            self.client = self

        def close(self):
            pass

        def submit_segment(self, prompt, duration, frame, **options):
            submissions.append((frame, options))
            if frame == b"reference":
                raise VideoProviderError(
                    "VIDEO_REFERENCE_REJECTED",
                    provider_status="rejected",
                    provider_error_code=REJECTION,
                )
            task = f"task-{len(submissions)}"
            record(MODEL, "submitted", {
                "requested_duration_seconds": duration,
                "has_reference_video": bool(options.get("reference_video_url")),
            }, 0, task)
            return task

        def fetch_segment(self, task, duration):
            record(MODEL, "succeeded", {"completion_tokens": 324900}, 0, task)
            return ProviderOutput(b"clip", "video/mp4", "mp4", {})

    monkeypatch.setattr(segmented, "VolcengineSeedanceProvider", Provider)
    run = client.post("/v1/production/runs", json=payload).json()
    endpoint = f"/v1/production/runs/{run['id']}/execute"
    assert client.post(endpoint).json()["status"] == "running"
    failed = client.post(endpoint).json()
    assert failed["status"] == "failed"
    assert failed["error_message"] == "VIDEO_REFERENCE_REJECTED"
    return failed, submissions


def add_reference(run, *, content=b"replacement", **overrides):
    with SessionLocal() as db:
        project = db.get(ScriptProject, UUID(run["project_id"]))
        values = {
            "tenant_id": project.tenant_id,
            "subject_id": project.subject_id,
            "kind": "photo",
            "mime_type": "image/png",
            "original_filename": "replacement.png",
            "byte_size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "storage_key": f"test/{uuid4()}.png",
            "status": "ready",
            "consent_status": "granted",
        }
        values.update(overrides)
        asset = SourceAsset(**values)
        db.add(asset)
        db.commit()
        private_storage().put(asset.storage_key, content)
        return str(asset.id)


def test_legacy_rejection_requires_explicit_retry_and_preserves_completed_segments(
    client,
    blocked_run,
):
    run, submissions = blocked_run
    with SessionLocal() as db:
        row = db.get(ProductionRun, UUID(run["id"]))
        row.error_message = "VIDEO_PROVIDER_REQUEST_FAILED"
        db.commit()
    wallet = client.get("/v1/wallet").json()
    current = client.get("/v1/production/runs").json()[0]
    assert current["error_message"] == "VIDEO_REFERENCE_REJECTED"
    assert current["recovery"]["segment_index"] == 1
    endpoint = f"/v1/production/runs/{run['id']}/execute"
    result = client.post(endpoint)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "VIDEO_REFERENCE_REJECTED"
    assert client.get("/v1/wallet").json() == wallet
    assert len(submissions) == 2
    with SessionLocal() as db:
        assert (
            db.get(ProductionRun, UUID(run["id"])).error_message == "VIDEO_PROVIDER_REQUEST_FAILED"
        )
    before = copy.deepcopy(current["output_manifest"]["segments"][0])
    retry_url = f"/v1/jobs/{run['job_id']}/retry"
    assert client.post(retry_url).status_code == 200
    reserved = client.get("/v1/wallet").json()
    assert client.post(retry_url).status_code == 409
    assert client.get("/v1/wallet").json() == reserved
    failed = client.post(endpoint).json()
    assert failed["status"] == "failed"
    assert failed["error_message"] == "VIDEO_REFERENCE_REJECTED"
    assert failed["output_manifest"]["segments"][0] == before
    history = failed["output_manifest"]["segments"][1]["reference_history"]
    assert history[-1]["action"] == "retry_same_reference"
    assert history[-1]["previous_provider_error_code"] == REJECTION
    assert len(submissions) == 3
    assert submissions[-1] == submissions[-2]
    assert client.get("/v1/wallet").json()["available_cents"] == wallet["available_cents"]
    assert client.get("/v1/wallet").json()["frozen_cents"] == 0


def test_same_reference_retry_can_succeed_and_bills_each_success_once(
    client, monkeypatch, blocked_run,
):
    run, submissions = blocked_run
    before = copy.deepcopy(run["output_manifest"]["segments"][0])

    def accept(self, prompt, duration, frame, **options):
        submissions.append((frame, options))
        task = f"task-{len(submissions)}"
        record(MODEL, "submitted", {"requested_duration_seconds": duration}, 0, task)
        return task

    monkeypatch.setattr(segmented.VolcengineSeedanceProvider, "submit_segment", accept)
    assert client.post(f"/v1/jobs/{run['job_id']}/retry").status_code == 200
    endpoint = f"/v1/production/runs/{run['id']}/execute"
    assert client.post(endpoint).json()["status"] == "running"
    done = client.post(endpoint).json()
    assert done["status"] == "completed"
    assert done["output_manifest"]["segments"][0] == before
    assert done["output_manifest"]["billing"]["charged_cents"] == 2241
    assert len(submissions) == 3
    assert submissions[-1] == submissions[-2]
    wallet = client.get("/v1/wallet").json()
    assert wallet["frozen_cents"] == 0
    assert client.post(endpoint).json()["status"] == "completed"
    assert client.get("/v1/wallet").json() == wallet


def test_replace_reference_resumes_remaining_segment_and_bills_each_success_once(
    client, blocked_run
):
    run, submissions = blocked_run
    reference = add_reference(run)
    url = f"/v1/production/runs/{run['id']}"
    before = copy.deepcopy(run["output_manifest"]["segments"][0])
    result = client.post(url + "/reference", json={"reference_asset_id": reference})
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "queued"
    assert result.json()["output_manifest"]["segments"][0] == before
    assert (
        client.post(url + "/reference", json={"reference_asset_id": reference}).status_code == 409
    )
    assert client.post(url + "/execute").json()["status"] == "running"
    done = client.post(url + "/execute").json()
    assert done["status"] == "completed"
    assert done["output_manifest"]["billing"]["charged_cents"] == 2241
    assert client.post(url + "/execute").json()["status"] == "completed"
    assert len(submissions) == 3
    assert submissions[-1] == (b"replacement", {"reference_mime": "image/png"})
    assert client.get("/v1/wallet").json()["frozen_cents"] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"subject_id": uuid4()},
        {"tenant_id": uuid4()},
        {"kind": "document"},
        {"mime_type": "image/svg+xml"},
        {"byte_size": 11 * 1024 * 1024},
        {"status": "processing"},
        {"consent_status": "revoked"},
        {"consent_status": "unknown"},
    ],
)
def test_invalid_reference_does_not_reserve_or_change_run(client, blocked_run, change):
    run, submissions = blocked_run
    reference = add_reference(run, **change)
    wallet = client.get("/v1/wallet").json()
    result = client.post(
        f"/v1/production/runs/{run['id']}/reference", json={"reference_asset_id": reference}
    )
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "VIDEO_REFERENCE_INVALID"
    assert client.get("/v1/wallet").json() == wallet
    assert client.get("/v1/production/runs").json()[0]["status"] == "failed"
    assert len(submissions) == 2


def test_partial_preview_is_tenant_scoped_and_never_exposes_incomplete_segments(
    client, blocked_run
):
    run, _ = blocked_run
    url = f"/v1/production/runs/{run['id']}"
    content = client.get(url + "/segments/0/content")
    assert content.status_code == 200
    assert content.content == b"clip"
    assert content.headers["content-type"] == "video/mp4"
    for index in (-1, 1, 2):
        assert client.get(url + f"/segments/{index}/content").status_code == 404
    assert (
        client.get(url + "/segments/0/content", headers={"X-Tenant-ID": str(uuid4())}).status_code
        == 404
    )
    reference = add_reference(run)
    assert (
        client.post(
            url + "/reference",
            json={"reference_asset_id": reference},
            headers={"X-Tenant-ID": str(uuid4())},
        ).status_code
        == 404
    )


def test_replacement_rejection_allows_same_file_on_explicit_retry(
    client,
    monkeypatch,
    blocked_run,
):
    run, _ = blocked_run
    balance_before = client.get("/v1/wallet").json()["available_cents"]
    reference = add_reference(run)
    url = f"/v1/production/runs/{run['id']}"
    assert (
        client.post(url + "/reference", json={"reference_asset_id": reference}).status_code == 200
    )

    def reject(self, *args, **kwargs):
        raise VideoProviderError(
            "VIDEO_REFERENCE_REJECTED",
            provider_status="rejected",
            provider_error_code=REJECTION,
        )

    monkeypatch.setattr(segmented.VolcengineSeedanceProvider, "submit_segment", reject)
    failed = client.post(url + "/execute").json()
    assert failed["recovery"]["rejected_asset_ids"] == [reference]
    wallet = client.get("/v1/wallet").json()
    assert wallet["available_cents"] == balance_before
    assert wallet["frozen_cents"] == 0
    assert (
        client.post(url + "/reference", json={"reference_asset_id": reference}).status_code == 200
    )
    # Duplicate clicks while queued do not reserve or submit another attempt.
    reserved = client.get("/v1/wallet").json()
    assert client.post(f"/v1/jobs/{run['job_id']}/retry").status_code == 409
    assert client.get("/v1/wallet").json() == reserved
    failed = client.post(url + "/execute").json()
    assert failed["error_message"] == "VIDEO_REFERENCE_REJECTED"
    assert client.get("/v1/wallet").json()["available_cents"] == wallet["available_cents"]
    assert client.post(f"/v1/jobs/{run['job_id']}/retry").status_code == 200


def test_rejected_hash_is_history_not_a_file_ban(client, blocked_run):
    run, submissions = blocked_run
    reference = add_reference(run, content=b"reference")
    url = f"/v1/production/runs/{run['id']}"
    assert (
        client.post(url + "/reference", json={"reference_asset_id": reference}).status_code == 200
    )
    assert client.post(url + "/execute").json()["error_message"] == "VIDEO_REFERENCE_REJECTED"
    assert len(submissions) == 3


def test_explicit_retry_validates_consent_before_reserving(client, blocked_run):
    run, _ = blocked_run
    reference = add_reference(run, consent_status="revoked")
    with SessionLocal() as db:
        row = db.get(ProductionRun, UUID(run["id"]))
        manifest = copy.deepcopy(row.output_manifest)
        manifest["segments"][1]["reference_asset_id"] = reference
        row.output_manifest = manifest
        db.commit()
    wallet = client.get("/v1/wallet").json()
    result = client.post(f"/v1/jobs/{run['job_id']}/retry")
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "VIDEO_REFERENCE_INVALID"
    assert client.get("/v1/wallet").json() == wallet


def test_retry_with_insufficient_balance_preserves_rejection(client, blocked_run):
    run, _ = blocked_run
    with SessionLocal() as db:
        db.get(Wallet, get_settings().default_tenant_id).bonus_cents = 0
        db.commit()
    before = client.get("/v1/production/runs").json()[0]
    result = client.post(f"/v1/jobs/{run['job_id']}/retry")
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "WALLET_INSUFFICIENT_BALANCE"
    assert client.get("/v1/production/runs").json()[0] == before


def test_no_balance_rejects_reference_change_atomically(client, blocked_run):
    run, _ = blocked_run
    reference = add_reference(run)
    with SessionLocal() as db:
        wallet = db.get(Wallet, get_settings().default_tenant_id)
        wallet.bonus_cents = 0
        db.commit()
    before = client.get("/v1/production/runs").json()[0]
    result = client.post(
        f"/v1/production/runs/{run['id']}/reference", json={"reference_asset_id": reference}
    )
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "WALLET_INSUFFICIENT_BALANCE"
    assert client.get("/v1/production/runs").json()[0] == before


def test_terminal_cloud_moderation_keeps_its_specific_error(monkeypatch):
    monkeypatch.setattr(get_settings(), "volcengine_api_key", "synthetic")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"status": "failed", "error": {"code": REJECTION}},
            )
        )
    )
    provider = VolcengineSeedanceProvider(client=client)
    with pytest.raises(VideoProviderError) as error:
        provider.fetch_segment("task-rejected", 15)
    assert error.value.code == "VIDEO_REFERENCE_REJECTED"
    assert error.value.provider_status == "failed"
    client.close()

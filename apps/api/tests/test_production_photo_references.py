import base64
import copy
import hashlib
import json
import time
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from test_segmented_production import setup_pipeline
from test_video_plan_repair import example, fake_client
from test_video_recovery import add_reference

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.evidence.models import SourceAsset
from lifereel_api.modules.evidence.storage import private_storage
from lifereel_api.modules.interview.models import Chapter
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.production import continuation, planning, segmented
from lifereel_api.modules.production.models import ProductionRun
from lifereel_api.modules.production.providers import (
    ProviderOutput,
    VideoProviderError,
    VolcengineSeedanceProvider,
)
from lifereel_api.modules.script.models import ScriptScene


@pytest.fixture
def photo_pipeline(client, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "local_storage_path", str(tmp_path))
    payload = setup_pipeline(client, monkeypatch)
    with SessionLocal() as db:
        scene = db.get(ScriptScene, UUID(payload["scene_id"]))
        chapter = db.scalar(select(Chapter).where(Chapter.tenant_id == scene.tenant_id))
        scene.chapter_id = chapter.id
        db.commit()
        chapter_id = chapter.id
    asset_id = add_reference(payload, chapter_id=chapter_id)
    requests, plans, fetches = [], [], []
    original_plan = segmented.plan_video

    def plan(*args, **kwargs):
        plans.append(kwargs)
        return original_plan(*args, **kwargs)

    def handler(request):
        assert request.method == "POST"
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": f"task-{len(requests)}"})

    def provider(options):
        return VolcengineSeedanceProvider(
            options=options, client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    def fetch(self, task_id, duration):
        fetches.append(task_id)
        return ProviderOutput(
            b"clip", "video/mp4", "mp4", {
                "last_frame_mime": "image/png",
                "original": self.original_metadata({
                    "id": task_id, "model": self.model, "created_at": time.time(),
                }, b"clip"),
            },
            last_frame=b"official-tail",
        )

    monkeypatch.setattr(segmented, "plan_video", plan)
    monkeypatch.setattr(segmented, "VolcengineSeedanceProvider", provider)
    monkeypatch.setattr(VolcengineSeedanceProvider, "fetch_segment", fetch)
    monkeypatch.setattr(segmented, "prepare_original", continuation.prepare_original)
    return payload, asset_id, requests, plans, fetches


def start(client, payload):
    response = client.post("/v1/production/runs", json=payload)
    assert response.status_code == 201, response.text
    run = response.json()
    return run, f"/v1/production/runs/{run['id']}/execute"


def image_content(content):
    return {
        "type": "image_url", "role": "first_frame",
        "image_url": {"url": "data:image/png;base64," + base64.b64encode(content).decode()},
    }


def test_selected_chapter_photo_reaches_http_request_then_official_tail_is_used(
    client, photo_pipeline,
):
    payload, photo_id, requests, plans, _ = photo_pipeline
    run, endpoint = start(client, payload)
    assert run["output_manifest"]["reference_package"]["character_reference"] == photo_id
    first = client.post(endpoint).json()
    assert first["status"] == "running", first
    assert plans[0]["has_portrait"] is True
    assert requests[0]["content"][1] == image_content(b"replacement")
    segment = first["output_manifest"]["segments"][0]
    assert segment["reference_asset_id"] == photo_id
    assert segment["reference_kind"] == "uploaded_image"
    assert segment["reference_sha256"] == hashlib.sha256(b"replacement").hexdigest()
    second = client.post(endpoint).json()
    assert second["status"] == "running", second
    assert requests[1]["content"][1] == image_content(b"official-tail")
    assert second["output_manifest"]["segments"][1]["reference_kind"] == "official_tail"
    assert client.post(endpoint).json()["status"] == "completed"
    assert client.post(endpoint).json()["status"] == "completed"
    assert len(requests) == 2


@pytest.mark.parametrize("replacement", [False, True])
def test_already_planned_run_binds_photo_without_overriding_manual_reference(
    client, photo_pipeline, replacement,
):
    payload, photo_id, requests, _, _ = photo_pipeline
    run, endpoint = start(client, payload)
    manual_id = add_reference(run, content=b"manual") if replacement else None
    with SessionLocal() as db:
        row = db.get(ProductionRun, UUID(run["id"]))
        manifest = copy.deepcopy(row.output_manifest)
        manifest["plan"] = {"voice": "test", "continuity": "test"}
        manifest["segments"] = [{
            "status": "pending", "duration_seconds": 15, "narration": "test",
            "visual_prompt": "test",
        }]
        if manual_id:
            manifest["segments"][0]["reference_asset_id"] = manual_id
        row.output_manifest = manifest
        db.commit()
    result = client.post(endpoint).json()
    assert result["status"] == "running", result
    assert result["output_manifest"]["segments"][0]["reference_asset_id"] == (manual_id or photo_id)
    assert requests[0]["content"][1] == image_content(b"manual" if replacement else b"replacement")


@pytest.mark.parametrize("change", [
    {"consent_status": "revoked"}, {"consent_status": "unknown"},
    {"status": "processing"}, {"subject_id": uuid4()}, {"tenant_id": uuid4()},
    {"mime_type": "image/svg+xml"}, {"byte_size": 11 * 1024 * 1024},
])
def test_selected_photo_is_revalidated_before_any_model_request(client, photo_pipeline, change):
    payload, photo_id, requests, plans, _ = photo_pipeline
    _, endpoint = start(client, payload)
    with SessionLocal() as db:
        asset = db.get(SourceAsset, UUID(photo_id))
        for key, value in change.items():
            setattr(asset, key, value)
        db.commit()
    result = client.post(endpoint).json()
    assert result["status"] == "failed", result
    assert result["error_message"] == "VIDEO_REFERENCE_INVALID"
    assert requests == plans == []


@pytest.mark.parametrize("content", [b"", b"changed"])
def test_invalid_photo_content_never_falls_back_to_text_only(client, photo_pipeline, content):
    payload, photo_id, requests, _, _ = photo_pipeline
    _, endpoint = start(client, payload)
    with SessionLocal() as db:
        asset = db.get(SourceAsset, UUID(photo_id))
        private_storage().root.joinpath(asset.storage_key).write_bytes(content)
    result = client.post(endpoint).json()
    assert result["status"] == "failed", result
    assert result["error_message"] == "VIDEO_REFERENCE_INVALID"
    assert requests == []


@pytest.mark.parametrize("kind", ["none", "video"])
def test_packages_without_photo_keep_text_generation(client, photo_pipeline, kind):
    payload, photo_id, requests, plans, _ = photo_pipeline
    with SessionLocal() as db:
        asset = db.get(SourceAsset, UUID(photo_id))
        if kind == "none":
            asset.consent_status = "unknown"
        else:
            asset.kind = "video"
            asset.mime_type = "video/mp4"
        db.commit()
    _, endpoint = start(client, payload)
    assert client.post(endpoint).json()["status"] == "running"
    assert plans[0]["has_portrait"] is False
    assert len(requests[0]["content"]) == 1


def test_timed_out_photo_task_is_fetched_without_resubmission(client, monkeypatch, photo_pipeline):
    payload, _, requests, _, _ = photo_pipeline
    original_fetch = VolcengineSeedanceProvider.fetch_segment
    attempts = []

    def fetch(self, task_id, duration):
        attempts.append(task_id)
        if len(attempts) == 1:
            raise VideoProviderError("VIDEO_PROVIDER_TIMEOUT", task_id=task_id)
        return original_fetch(self, task_id, duration)

    monkeypatch.setattr(VolcengineSeedanceProvider, "fetch_segment", fetch)
    run, endpoint = start(client, payload)
    assert client.post(endpoint).json()["status"] == "failed"
    assert client.post(f"/v1/jobs/{run['job_id']}/retry").status_code == 200
    assert client.post(endpoint).json()["status"] == "running"
    assert attempts == ["task-1", "task-1"]
    assert len(requests) == 1


def test_photo_fingerprint_allows_new_generation_but_deduplicates_repeat_clicks(
    client, photo_pipeline,
):
    payload, _, _, _, _ = photo_pipeline
    old, _ = start(client, payload)
    with SessionLocal() as db:
        row = db.get(ProductionRun, UUID(old["id"]))
        job = db.get(Job, row.job_id)
        config = row.output_manifest["generation_config"]
        old_fingerprint = hashlib.sha256(
            json.dumps(config, sort_keys=True).encode()
        ).hexdigest()[:16]
        job.idempotency_key = job.idempotency_key.rsplit(":", 1)[0] + ":" + old_fingerprint
        row.status = job.status = "completed"
        db.commit()
    current, _ = start(client, payload)
    assert current["id"] != old["id"]
    assert start(client, payload)[0]["id"] == current["id"]
    with SessionLocal() as db:
        chapter_id = db.get(ScriptScene, UUID(payload["scene_id"])).chapter_id
    add_reference(payload, content=b"new-photo", chapter_id=chapter_id, quality_score=1)
    changed, _ = start(client, payload)
    assert changed["id"] not in {old["id"], current["id"]}
    assert start(client, payload)[0]["id"] == changed["id"]
    with SessionLocal() as db:
        assert all(len(job.idempotency_key) <= 180 for job in db.scalars(select(Job)))


def test_planner_receives_portrait_availability(monkeypatch):
    scenes, valid = example()
    requests = fake_client(monkeypatch, [valid])
    planning.plan_video(scenes, {}, has_portrait=True)
    assert requests[0]["has_portrait"] is True

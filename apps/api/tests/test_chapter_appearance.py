import base64
import copy
import io
import json
import wave
from uuid import UUID, uuid4

import httpx
import pytest
from test_segmented_production import setup_pipeline
from test_video_recovery import add_reference

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.evidence import redraw
from lifereel_api.modules.evidence.models import SourceAsset
from lifereel_api.modules.production import segmented
from lifereel_api.modules.production.locking import execution_lock
from lifereel_api.modules.production.providers import ProviderOutput, VolcengineSeedanceProvider
from lifereel_api.modules.script.models import ScriptScene
from lifereel_api.providers import siliconflow

SOURCE = b"\x89PNG\r\n\x1a\nsynthetic-source"
OUTPUT = b"\x89PNG\r\n\x1a\nsynthetic-redraw"


@pytest.fixture
def appearance_pipeline(client, monkeypatch, tmp_path):
    payload = setup_pipeline(client, monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "video_reference_style", "color_redraw")
    monkeypatch.setattr(settings, "photo_redraw_provider", "mock")
    monkeypatch.setattr(settings, "job_queue_backend", "database")
    photo = add_reference(payload, content=SOURCE)
    requests, redraw_calls = [], []

    def redraw(content, mime):
        redraw_calls.append(content)
        return siliconflow.RedrawOutput(OUTPUT + content[-1:], "image/png")

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": f"task-{len(requests)}"})

    def provider(options):
        return VolcengineSeedanceProvider(
            options=options, client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    monkeypatch.setattr(siliconflow, "redraw", redraw)
    monkeypatch.setattr(segmented, "VolcengineSeedanceProvider", provider)
    monkeypatch.setattr(VolcengineSeedanceProvider, "fetch_segment", lambda *_:
                        ProviderOutput(b"clip", "video/mp4", "mp4", {}))
    return payload, photo, requests, redraw_calls


def refs_url(payload):
    return f"/v1/scripts/{payload['project_id']}/scenes/{payload['scene_id']}/references"


def test_chapter_selection_is_shared_versioned_clearable_and_tenant_scoped(
    client, appearance_pipeline,
):
    payload, photo, _, _ = appearance_pipeline
    url = refs_url(payload)
    assert [a["id"] for a in client.get(url).json()] == [photo]
    assert client.get(url, headers={"X-Tenant-ID": str(uuid4())}).status_code == 404
    run = client.post("/v1/production/runs", json=payload).json()
    response = client.patch(url, json={"expected_version": 1, "asset_ids": []})
    assert response.status_code == 200, response.text
    assert response.json()["version_number"] == 2
    assert client.get(url).json() == []
    assert client.patch(url, json={"expected_version": 1, "asset_ids": [photo]}).status_code == 409
    new_run = client.post("/v1/production/runs", json=payload).json()
    assert new_run["id"] != run["id"]
    assert new_run["output_manifest"]["reference_package"]["source_assets"] == []
    old_run = next(item for item in client.get("/v1/production/runs").json()
                   if item["id"] == run["id"])
    assert old_run["output_manifest"]["reference_package"]["source_assets"] == [photo]


@pytest.mark.parametrize("change", [{"subject_id": uuid4()}, {"consent_status": "revoked"}])
def test_invalid_material_selection_never_updates_version_or_wallet(
    client, appearance_pipeline, change,
):
    payload, photo, _, _ = appearance_pipeline
    with SessionLocal() as db:
        source = db.get(SourceAsset, UUID(photo))
        for key, value in change.items():
            setattr(source, key, value)
        db.commit()
    wallet = client.get("/v1/wallet").json()
    response = client.patch(refs_url(payload), json={"expected_version": 1, "asset_ids": [photo]})
    assert response.status_code == 422
    assert client.get(f"/v1/scripts/{payload['project_id']}").json()["version_number"] == 1
    assert client.get("/v1/wallet").json() == wallet


def test_redraw_reaches_video_request_and_is_reused_across_segments_and_runs(
    client, appearance_pipeline,
):
    payload, photo, requests, redraw_calls = appearance_pipeline
    run = client.post("/v1/production/runs", json=payload).json()
    endpoint = f"/v1/production/runs/{run['id']}/execute"
    first = client.post(endpoint).json()
    assert first["status"] == "running", first
    sent = requests[0]["content"][1]
    assert sent["role"] == "reference_image"
    assert base64.b64decode(sent["image_url"]["url"].split(",", 1)[1]) == OUTPUT + SOURCE[-1:]
    assert "彩色二维手绘" not in requests[0]["content"][0]["text"]
    saved = first["output_manifest"]["prepared_references"][photo]
    assert saved["asset_id"] != photo
    assert client.post(endpoint).json()["status"] == "running"
    assert client.post(endpoint).json()["status"] == "completed"
    assert redraw_calls == [SOURCE]
    assert requests[1]["content"][1]["role"] == "first_frame"
    assert client.patch(
        refs_url(payload), json={"expected_version": 1, "asset_ids": [photo]},
    ).status_code == 200
    new_run = client.post("/v1/production/runs", json=payload).json()
    assert client.post(f"/v1/production/runs/{new_run['id']}/execute").json()["status"] == "running"
    assert redraw_calls == [SOURCE]


def test_new_prompt_uses_new_run_and_new_image_without_reusing_previous_redraw(
    client, monkeypatch, appearance_pipeline,
):
    payload, photo, requests, redraw_calls = appearance_pipeline
    current_version = siliconflow.PROMPT_VERSION
    with monkeypatch.context() as old:
        old.setattr(siliconflow, "PROMPT_VERSION", "color-redraw-v1")
        old.setattr(siliconflow, "PROMPT", "Previous color redraw prompt")
        old_run = client.post("/v1/production/runs", json=payload).json()
        old_result = client.post(f"/v1/production/runs/{old_run['id']}/execute").json()
        assert old_result["status"] == "running"
    settings = client.get("/v1/production/settings").json()
    assert settings["reference_prompt_version"] == current_version

    def annotate(content, mime):
        redraw_calls.append(content)
        return siliconflow.RedrawOutput(OUTPUT + b"-label-v2", "image/png")

    monkeypatch.setattr(siliconflow, "redraw", annotate)
    new_run = client.post("/v1/production/runs", json=payload).json()
    assert new_run["id"] != old_run["id"]
    result = client.post(f"/v1/production/runs/{new_run['id']}/execute").json()
    assert result["status"] == "running"
    assert result["output_manifest"]["prepared_references"][photo]["asset_id"] != (
        old_result["output_manifest"]["prepared_references"][photo]["asset_id"]
    )
    sent = requests[-1]["content"][1]["image_url"]["url"]
    assert base64.b64decode(sent.split(",", 1)[1]) == OUTPUT + b"-label-v2"
    assert "彩色二维手绘" not in requests[-1]["content"][0]["text"]
    assert redraw_calls == [SOURCE, SOURCE]


def test_redraw_failure_stops_before_video_and_never_falls_back_to_original(
    client, monkeypatch, appearance_pipeline,
):
    payload, _, requests, _ = appearance_pipeline

    def reject(*_):
        raise ApiError(422, ErrorCode.PHOTO_REDRAW_REJECTED)

    monkeypatch.setattr(siliconflow, "redraw", reject)
    wallet = client.get("/v1/wallet").json()
    run = client.post("/v1/production/runs", json=payload).json()
    endpoint = f"/v1/production/runs/{run['id']}/execute"
    assert client.post(endpoint).json()["error_message"] == "PHOTO_REDRAW_REJECTED"
    assert requests == []
    assert client.get("/v1/wallet").json()["available_cents"] == wallet["available_cents"]
    assert client.post(f"/v1/jobs/{run['job_id']}/retry").status_code == 409
    monkeypatch.setattr(siliconflow, "redraw", lambda *_: pytest.fail("No automatic redraw retry"))
    assert client.post(endpoint).json()["error_message"] == "PHOTO_REDRAW_REJECTED"
    assert requests == []


def test_transient_redraw_failure_retries_only_on_explicit_generation_retry(
    client, monkeypatch, appearance_pipeline,
):
    payload, _, requests, redraw_calls = appearance_pipeline
    redraw_impl = siliconflow.redraw

    def unavailable(*_):
        redraw_calls.append(SOURCE)
        raise ApiError(502, ErrorCode.PHOTO_REDRAW_FAILED)

    monkeypatch.setattr(siliconflow, "redraw", unavailable)
    run = client.post("/v1/production/runs", json=payload).json()
    endpoint = f"/v1/production/runs/{run['id']}/execute"
    assert client.post(endpoint).json()["error_message"] == "PHOTO_REDRAW_FAILED"
    assert client.post(endpoint).json()["error_message"] == "PHOTO_REDRAW_FAILED"
    assert redraw_calls == [SOURCE] and requests == []
    monkeypatch.setattr(siliconflow, "redraw", redraw_impl)
    assert client.post(f"/v1/jobs/{run['job_id']}/retry").status_code == 200
    result = client.post(endpoint).json()
    assert result["status"] == "running"
    assert result["output_manifest"]["redraw_retry_jobs"] == {}
    assert redraw_calls == [SOURCE, SOURCE] and len(requests) == 1


def test_running_redraw_is_waited_for_without_failing_production(client, appearance_pipeline):
    payload, photo, requests, redraw_calls = appearance_pipeline
    run = client.post("/v1/production/runs", json=payload).json()
    endpoint = f"/v1/production/runs/{run['id']}/execute"
    with SessionLocal() as db:
        asset = db.get(SourceAsset, UUID(photo))
        job = redraw.create(db, asset.tenant_id, asset.id)
        with execution_lock(db, job.id) as acquired:
            assert acquired
            result = client.post(endpoint).json()
            assert result["status"] == "running"
            assert requests == redraw_calls == []
    assert client.post(endpoint).json()["status"] == "running"
    assert len(requests) == len(redraw_calls) == 1


def audio(seconds):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * 8000 * seconds)
    return output.getvalue()


def test_selected_audio_is_sent_with_image_and_wrong_duration_fails_before_reserve(
    client, appearance_pipeline,
):
    payload, photo, requests, _ = appearance_pipeline
    wav = audio(3)
    sound = add_reference(payload, content=wav, kind="audio", mime_type="audio/wav")
    url = refs_url(payload)
    assert client.patch(
        url, json={"expected_version": 1, "asset_ids": [photo, sound]},
    ).status_code == 200
    run = client.post("/v1/production/runs", json=payload).json()
    assert client.post(f"/v1/production/runs/{run['id']}/execute").json()["status"] == "running"
    sent = requests[0]["content"][2]
    assert sent["role"] == "reference_audio"
    assert base64.b64decode(sent["audio_url"]["url"].split(",", 1)[1]) == wav
    long_audio = add_reference(payload, content=audio(16), kind="audio", mime_type="audio/wav")
    assert client.patch(
        url, json={"expected_version": 2, "asset_ids": [photo, long_audio]},
    ).status_code == 200
    wallet = client.get("/v1/wallet").json()
    response = client.post("/v1/production/runs", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VIDEO_AUDIO_REFERENCE_INVALID"
    assert client.get("/v1/wallet").json() == wallet


def test_audio_only_is_saved_but_cannot_silently_generate_without_it(
    client, appearance_pipeline,
):
    payload, _, requests, _ = appearance_pipeline
    sound = add_reference(payload, content=audio(3), kind="audio", mime_type="audio/wav")
    assert client.patch(
        refs_url(payload), json={"expected_version": 1, "asset_ids": [sound]},
    ).status_code == 200
    response = client.post("/v1/production/runs", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VIDEO_AUDIO_REQUIRES_IMAGE"
    assert requests == []


def test_automatic_materials_ignore_audio_without_numeric_duration(client, appearance_pipeline):
    payload, photo, _, _ = appearance_pipeline
    sound = add_reference(payload, content=audio(3), kind="audio", mime_type="audio/wav")
    with SessionLocal() as db:
        asset = db.get(SourceAsset, UUID(sound))
        asset.metadata_json = {"duration_seconds": "unknown"}
        db.commit()
    response = client.get(refs_url(payload))
    assert response.status_code == 200
    assert [asset["id"] for asset in response.json()] == [photo]


def test_source_revocation_after_snapshot_prevents_redraw_and_video(
    client, appearance_pipeline,
):
    payload, photo, requests, redraw_calls = appearance_pipeline
    run = client.post("/v1/production/runs", json=payload).json()
    with SessionLocal() as db:
        db.get(SourceAsset, UUID(photo)).consent_status = "revoked"
        db.commit()
    failed = client.post(f"/v1/production/runs/{run['id']}/execute").json()
    assert failed["error_message"] == "VIDEO_REFERENCE_INVALID"
    assert requests == redraw_calls == []


def test_changing_scene_selection_does_not_change_queued_input(client, appearance_pipeline):
    payload, photo, requests, _ = appearance_pipeline
    second = add_reference(payload, content=SOURCE + b"2")
    assert client.patch(
        refs_url(payload), json={"expected_version": 1, "asset_ids": [photo, second]},
    ).status_code == 200
    run = client.post("/v1/production/runs", json=payload).json()
    snapshot = copy.deepcopy(run["output_manifest"]["reference_package"])
    with SessionLocal() as db:
        db.get(ScriptScene, UUID(payload["scene_id"])).reference_asset_ids = []
        db.commit()
    result = client.post(f"/v1/production/runs/{run['id']}/execute").json()
    assert result["output_manifest"]["reference_package"] == snapshot
    assert result["output_manifest"]["reference_package"]["source_assets"] == [photo, second]
    assert len(requests[0]["content"]) == 3


def test_video_moderation_of_prepared_images_still_blocks_automatic_execution(
    client, monkeypatch, appearance_pipeline,
):
    payload, _, _, redraw_calls = appearance_pipeline
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {
            "code": "InputImageSensitiveContentDetected.PrivacyInformation",
        }})

    monkeypatch.setattr(segmented, "VolcengineSeedanceProvider", lambda options:
                        VolcengineSeedanceProvider(
                            options=options,
                            client=httpx.Client(transport=httpx.MockTransport(handler)),
                        ))
    run = client.post("/v1/production/runs", json=payload).json()
    endpoint = f"/v1/production/runs/{run['id']}/execute"
    assert client.post(endpoint).json()["error_message"] == "VIDEO_REFERENCE_REJECTED"
    assert client.post(endpoint).status_code == 409
    assert len(requests) == len(redraw_calls) == 1
    assert client.post(f"/v1/jobs/{run['job_id']}/retry").status_code == 200
    assert client.post(endpoint).json()["error_message"] == "VIDEO_REFERENCE_REJECTED"
    assert len(requests) == 2 and len(redraw_calls) == 1
    assert requests[0] == requests[1]

from uuid import UUID, uuid4

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.jobs import service as jobs
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.production import service
from lifereel_api.modules.production.models import ProductionRun
from lifereel_api.modules.production.providers import ProviderOutput
from lifereel_api.modules.script.models import ScriptProject, ScriptScene, ScriptShot


def make_script(client):
    person = client.post("/v1/persons", json={"display_name": "章节影像测试"}).json()
    with SessionLocal() as db:
        project = ScriptProject(
            tenant_id=UUID(person["tenant_id"]), subject_id=UUID(person["id"]),
            title="人生", mode="multi_chapter",
        )
        db.add(project)
        db.flush()
        scenes = [
            ScriptScene(
                tenant_id=project.tenant_id, project_id=project.id,
                heading=f"Chapter {index}", order_index=index,
                narration=f"Narration {index}", visual_prompt=f"Visual {index}",
                duration_seconds=30,
            )
            for index in (1, 2)
        ]
        db.add_all(scenes)
        db.commit()
        return project, scenes


def test_chapter_render_uses_frozen_snapshot_and_separate_idempotency(client, monkeypatch):
    project, scenes = make_script(client)
    captured = []

    class Provider:
        def render(self, title, inputs):
            captured.append((title, inputs))
            return ProviderOutput(
                content=b"{}", mime_type="application/json", extension="json", parameters={}
            )

    monkeypatch.setattr(service, "get_video_provider", lambda _: Provider())
    monkeypatch.setattr(get_settings(), "execute_mock_jobs_inline", False)
    monkeypatch.setattr(jobs, "enqueue", lambda _: None)
    with SessionLocal() as db:
        for original in scenes:
            scene = db.get(ScriptScene, original.id)
            scene.plot = f"Plot {scene.order_index}"
            scene.dialogues = [{"kind": "narration", "speaker": "Test", "text": scene.narration}]
            db.add(ScriptShot(
                tenant_id=project.tenant_id, scene_id=scene.id, order_index=1,
                shot_type="wide", visual_prompt=f"Shot {scene.order_index}", duration_seconds=30,
            ))
        db.commit()
    payload = {"project_id": str(project.id), "scene_id": str(scenes[0].id), "provider": "mock"}
    response = client.post("/v1/production/runs", json=payload)
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "queued"
    assert len(run["output_manifest"]["script_snapshot"]) == 1
    snapshot = run["output_manifest"]["script_snapshot"][0]
    assert snapshot["plot"] == "Plot 1"
    assert snapshot["dialogues"][0]["text"] == "Narration 1"
    assert len(snapshot["shots"]) == 1
    assert snapshot["shots"][0]["visual_prompt"] == "Shot 1"
    assert client.post("/v1/production/runs", json=payload).json()["id"] == run["id"]
    second = client.post(
        "/v1/production/runs", json={**payload, "scene_id": str(scenes[1].id)}
    ).json()
    assert second["id"] != run["id"]

    with SessionLocal() as db:
        scene = db.get(ScriptScene, scenes[0].id)
        scene.narration = "Changed after submission"
        scene.plot = "Updated plot"
        scene.dialogues = [{"kind": "narration", "speaker": "Test", "text": scene.narration}]
        shot = db.get(ScriptShot, UUID(snapshot["shots"][0]["id"]))
        shot.visual_prompt = "Updated shot"
        db.commit()
    executed = client.post(f"/v1/production/runs/{run['id']}/execute").json()
    assert executed["status"] == "completed"
    assert captured[0][0] == "Chapter 1"
    assert len(captured[0][1]) == 1
    assert captured[0][1][0]["narration"] == "Narration 1"
    assert executed["assets"][0]["scene_id"] == str(scenes[0].id)
    assert executed["output_manifest"]["script_snapshot"][0]["narration"] == "Narration 1"
    assert executed["output_manifest"]["script_snapshot"][0] == snapshot


def test_invalid_or_foreign_chapter_does_not_enqueue(client):
    project, _ = make_script(client)
    for payload in (
        {"project_id": str(project.id), "scene_id": str(uuid4())},
        {"project_id": str(uuid4())},
    ):
        response = client.post("/v1/production/runs", json={**payload, "provider": "mock"})
        assert response.status_code in (404, 409)
    assert client.get("/v1/production/runs").json() == []


def test_production_settings_expose_only_public_parameters(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "video_provider", "volcengine-seedance")
    monkeypatch.setattr(settings, "volcengine_video_duration", 5)
    monkeypatch.setattr(settings, "volcengine_video_generate_audio", False)
    data = client.get("/v1/production/settings").json()
    assert set(data) == {
        "provider", "model", "resolution", "ratio", "duration_seconds", "generate_audio",
        "mode", "max_segment_seconds", "reference_style", "reference_prompt_version",
    }
    assert data["duration_seconds"] == 5
    assert data["generate_audio"] is False
    assert data["reference_style"] == "original"
    assert data["reference_prompt_version"] is None


def test_retry_resets_production_status(client, monkeypatch):
    project, scenes = make_script(client)
    monkeypatch.setattr(get_settings(), "execute_mock_jobs_inline", False)
    monkeypatch.setattr(jobs, "enqueue", lambda _: None)
    run = client.post("/v1/production/runs", json={
        "project_id": str(project.id), "scene_id": str(scenes[0].id), "provider": "mock",
    }).json()
    with SessionLocal() as db:
        item = db.get(ProductionRun, UUID(run["id"]))
        job = db.get(Job, UUID(run["job_id"]))
        item.status = job.status = "failed"
        item.error_message = job.error_code = "VIDEO_PROVIDER_FAILED"
        db.commit()
        jobs.retry_job(db, project.tenant_id, job.id)
        db.refresh(item)
        assert item.status == "queued"
        assert item.error_message is None

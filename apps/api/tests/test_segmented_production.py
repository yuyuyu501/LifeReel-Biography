import copy
import subprocess
from uuid import UUID

import pytest
from test_production_chapters import make_script

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.jobs import service as jobs
from lifereel_api.modules.production import segmented
from lifereel_api.modules.production.media import assemble_videos, probe_video
from lifereel_api.modules.production.models import ProductionRun
from lifereel_api.modules.production.planning import segment_durations, validate_plan
from lifereel_api.modules.production.providers import ProviderOutput, VideoProviderError


@pytest.mark.parametrize(
    "duration,expected", [(4, [4]), (15, [15]), (16, [8, 8]), (30, [15, 15]), (31, [11, 10, 10])]
)
def test_duration_allocation(duration, expected):
    assert segment_durations(duration) == expected


@pytest.mark.parametrize("duration", [0, 3, 301])
def test_duration_bounds(duration):
    with pytest.raises(VideoProviderError):
        segment_durations(duration)


def test_plan_preserves_narration_and_duration():
    scenes = [{"id": "s1", "narration": "第一句。第二句。", "duration_seconds": 30}]
    plan = {
        "continuity": "纪实",
        "voice": "普通话",
        "segments": [
            {"scene_id": "s1", "narration": phrase, "duration_seconds": 15, "visual_prompt": "镜头"}
            for phrase in ["第一句。", "第二句。"]
        ],
    }
    assert validate_plan(plan, scenes)["segments"] == plan["segments"]
    for field, value in [("narration", "改写"), ("scene_id", "other"), ("duration_seconds", 14)]:
        invalid = copy.deepcopy(plan)
        invalid["segments"][0][field] = value
        with pytest.raises(ValueError):
            validate_plan(invalid, scenes)


def setup_pipeline(client, monkeypatch):
    project, scenes = make_script(client)
    settings = get_settings()
    monkeypatch.setattr(settings, "volcengine_api_key", "test-key")
    monkeypatch.setattr(settings, "volcengine_video_model", "doubao-seedance-2-0-mini-260615")
    monkeypatch.setattr(settings, "volcengine_video_generate_audio", True)
    monkeypatch.setattr(jobs, "enqueue", lambda _: None)
    monkeypatch.setattr(segmented, "require_media_tools", lambda: None)
    monkeypatch.setattr(segmented, "prepare_original", lambda *args: (
        b"reference", {}, {
            "kind": "official_tail", "sha256": "reference", "source_task_id": "task-1",
        },
    ))
    monkeypatch.setattr(
        segmented, "probe_video", lambda *_: {"duration_seconds": 15, "has_audio": True}
    )
    monkeypatch.setattr(
        segmented,
        "plan_video",
        lambda snapshot, subject, **kwargs: {
            "continuity": subject["display_name"],
            "voice": "男声",
            "segments": [
                {
                    "scene_id": snapshot[0]["id"],
                    "duration_seconds": 15,
                    "narration": text,
                    "visual_prompt": "画面",
                }
                for text in ["Narration ", "1"]
            ],
        },
    )
    monkeypatch.setattr(
        segmented,
        "assemble_videos",
        lambda paths, directory, config: (
            b"joined",
            {"duration_seconds": 30, "width": 1280, "height": 720, "has_audio": True},
        ),
    )
    payload = {
        "project_id": str(project.id),
        "scene_id": str(scenes[0].id),
        "provider": "volcengine-seedance",
    }
    return payload


def test_pipeline_resumes_task_without_paying_for_completed_or_pending_segments(
    client, monkeypatch
):
    payload = setup_pipeline(client, monkeypatch)
    submissions = []
    fetches = []

    class Provider:
        def __init__(self, options):
            self.client = self
            assert options["model"] == "doubao-seedance-2-0-mini-260615"

        def close(self):
            pass

        def submit_segment(self, prompt, duration, frame):
            submissions.append((duration, frame))
            return f"task-{len(submissions)}"

        def fetch_segment(self, task_id, duration):
            fetches.append(task_id)
            if task_id == "task-2" and fetches.count(task_id) == 1:
                raise VideoProviderError("VIDEO_PROVIDER_TIMEOUT", task_id=task_id)
            return ProviderOutput(b"clip", "video/mp4", "mp4", {})

    monkeypatch.setattr(segmented, "VolcengineSeedanceProvider", Provider)
    started = client.post("/v1/production/runs", json=payload)
    assert started.status_code == 201
    run = started.json()
    url = f"/v1/production/runs/{run['id']}/execute"
    first = client.post(url).json()
    assert first["status"] == "running"
    assert first["output_manifest"]["completed_segments"] == 1
    failed = client.post(url).json()
    assert failed["status"] == "failed"
    assert failed["output_manifest"]["segments"][1]["task_id"] == "task-2"
    assert client.post(f"/v1/jobs/{run['job_id']}/retry").status_code == 200
    resumed = client.post(url).json()
    assert resumed["output_manifest"]["completed_segments"] == 2
    completed = client.post(url).json()
    assert completed["status"] == "completed"
    assert completed["assets"][0]["generation_parameters"]["segment_count"] == 2
    assert submissions == [(15, None), (15, b"reference")]
    assert client.post(url).json()["id"] == completed["id"]
    assert len(submissions) == 2
    assert client.post("/v1/production/runs", json=payload).json()["id"] == run["id"]
    monkeypatch.setattr(get_settings(), "volcengine_video_generate_audio", False)
    assert client.post("/v1/production/runs", json=payload).json()["id"] != run["id"]


def test_unknown_submission_is_never_automatically_resubmitted(client, monkeypatch):
    payload = setup_pipeline(client, monkeypatch)
    run = client.post("/v1/production/runs", json=payload).json()
    with SessionLocal() as db:
        row = db.get(ProductionRun, UUID(run["id"]))
        manifest = copy.deepcopy(row.output_manifest)
        manifest["plan"] = {"voice": "test", "continuity": "test"}
        manifest["segments"] = [{"status": "submitting", "duration_seconds": 15}]
        row.output_manifest = manifest
        db.commit()
    response = client.post(f"/v1/production/runs/{run['id']}/execute").json()
    assert response["status"] == "failed"
    assert response["error_message"] == "VIDEO_SUBMISSION_UNCERTAIN"


def test_real_ffmpeg_assembly_keeps_audio_and_order(tmp_path):
    paths = []
    for index, color in enumerate(["red", "blue"]):
        path = tmp_path / f"input-{index}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color={color}:s=64x64:r=24",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={400 + index * 400}:sample_rate=48000",
                "-t",
                "1",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        paths.append(path)
    content, info = assemble_videos(
        paths,
        tmp_path,
        {
            "ratio": "16:9",
            "resolution": "720p",
            "generate_audio": True,
        },
    )
    assert content
    assert info["has_audio"] is True
    assert (info["width"], info["height"]) == (1280, 720)
    assert abs(info["duration_seconds"] - 2) < 0.15
    for timestamp, channel in [(0.5, 0), (1.5, 2)]:
        frame = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(timestamp),
                "-i",
                str(tmp_path / "chapter.mp4"),
                "-frames:v",
                "1",
                "-vf",
                "scale=1:1",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
        assert frame[channel] > frame[2 - channel] + 50


def test_missing_audio_is_not_silently_replaced(tmp_path):
    path = tmp_path / "silent.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=64x64:r=24",
            "-t",
            "1",
            "-c:v",
            "libx264",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    with pytest.raises(VideoProviderError):
        probe_video(path, require_audio=True)

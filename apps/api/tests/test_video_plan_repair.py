import copy
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from test_segmented_production import setup_pipeline

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.production import planning, segmented
from lifereel_api.modules.production.models import ProductionRun
from lifereel_api.modules.production.providers import VideoProviderError


def example():
    scenes = [{"id": "s1", "narration": "第一句。第二句。", "duration_seconds": 22}]
    plan = {
        "continuity": "纪实", "voice": "普通话",
        "segments": [
            {"scene_id": "s1", "end_offset": end,
             "visual_prompt": "镜头"}
            for end in [4, 8]
        ],
    }
    return scenes, plan


def fake_client(monkeypatch, responses):
    requests = []
    monkeypatch.setattr(get_settings(), "llm_provider", "openai-compatible")

    class Client:
        def __init__(self, *args):
            pass

        def capabilities(self):
            return SimpleNamespace(configured=True)

        def chat_json(self, system, user):
            requests.append(json.loads(user))
            item = responses[len(requests) - 1]
            if isinstance(item, Exception):
                raise item
            return item

    monkeypatch.setattr(planning, "OpenAICompatibleClient", Client)
    return requests


@pytest.mark.parametrize("duration,expected", [
    (22, [11, 11]), (31, [11, 10, 10]), (40, [14, 13, 13]), (30, [15, 15]),
])
def test_balanced_duration_unchanged(duration, expected):
    assert planning.segment_durations(duration) == expected


@pytest.mark.parametrize("kind,code", [
    ("boundary", "PLAN_BOUNDARY_INVALID"),
    ("count", "PLAN_SEGMENT_COUNT_MISMATCH"),
    ("chapter", "PLAN_CHAPTER_MISMATCH"),
    ("schema", "PLAN_SCHEMA_INVALID"),
])
def test_targeted_repair_receives_previous_result_and_specific_issue(monkeypatch, kind, code):
    scenes, valid = example()
    invalid = copy.deepcopy(valid)
    if kind == "boundary":
        invalid["segments"][0]["end_offset"] = 100
    elif kind == "count":
        invalid["segments"].pop()
    elif kind == "chapter":
        invalid["segments"][0]["scene_id"] = "other"
    else:
        del invalid["voice"]
    requests = fake_client(monkeypatch, [invalid, valid])
    recorded = []
    result = planning.plan_video(scenes, {}, on_failure=lambda *args: recorded.append(args))
    assert result == planning.materialize_plan(valid, scenes)
    assert "".join(part["narration"] for part in result["segments"]) == scenes[0]["narration"]
    correction = requests[1]["correction"]
    assert correction["issues"][0]["code"] == code
    assert json.loads(correction["previous_response"]) == invalid
    assert "秘密" not in json.dumps(recorded[0][0], ensure_ascii=False)
    assert recorded[0][1] == invalid
    assert requests[0]["allocations"] == [{"scene_id": "s1", "durations": [11, 11]}]


def test_malformed_json_is_captured_and_repaired(monkeypatch):
    scenes, valid = example()
    raw = '{"voice": "unfinished'
    requests = fake_client(monkeypatch, [json.JSONDecodeError("bad", raw, 9), valid])
    recorded = []
    assert planning.plan_video(
        scenes, {}, on_failure=lambda *args: recorded.append(args),
    ) == planning.materialize_plan(valid, scenes)
    assert recorded[0][0]["issues"] == [
        {"code": "PLAN_JSON_INVALID", "field": "$", "position": 9},
    ]
    assert recorded[0][1] == raw
    assert raw == json.loads(requests[1]["correction"]["previous_response"])


def test_three_attempt_limit_and_bounded_feedback(monkeypatch):
    scenes, _ = example()
    bad = {"private_text": "x" * 100000}
    requests = fake_client(monkeypatch, [bad] * 3)
    recorded = []
    with pytest.raises(VideoProviderError, match="VIDEO_PLAN_INVALID"):
        planning.plan_video(scenes, {}, on_failure=lambda *args: recorded.append(args))
    assert len(requests) == len(recorded) == 3
    assert requests[2]["correction"]["truncated"] is True
    assert len(requests[2]["correction"]["previous_response"]) == 24000


def test_request_failure_does_not_blindly_retry_or_save_exception_text(monkeypatch):
    scenes, _ = example()
    requests = fake_client(monkeypatch, [RuntimeError("credential must not be exposed")])
    recorded = []
    with pytest.raises(VideoProviderError, match="VIDEO_PLAN_FAILED"):
        planning.plan_video(scenes, {}, on_failure=lambda *args: recorded.append(args))
    assert len(requests) == 1
    assert recorded[0][0]["issues"][0]["code"] == "PLAN_REQUEST_FAILED"
    assert "credential" not in str(recorded)


def test_failure_checkpoint_survives_rollback_and_raw_stays_private(client, monkeypatch):
    payload = setup_pipeline(client, monkeypatch)
    stored = {}

    class Storage:
        def put(self, key, content):
            stored[key] = json.loads(content)

    monkeypatch.setattr(segmented, "private_storage", lambda: Storage())

    def invalid_plan(snapshot, subject, *, on_failure):
        for attempt in range(1, 4):
            on_failure({"attempt": attempt, "issues": [
                {"code": "PLAN_NARRATION_MISMATCH", "field": "segments.0.narration"},
            ]}, {"narration": "private family memory"})
        raise VideoProviderError("VIDEO_PLAN_INVALID")

    monkeypatch.setattr(segmented, "plan_video", invalid_plan)
    run = client.post("/v1/production/runs", json=payload).json()
    failed = client.post(f"/v1/production/runs/{run['id']}/execute").json()
    assert failed["error_message"] == "VIDEO_PLAN_INVALID"
    assert len(failed["output_manifest"]["planning_diagnostics"]) == 3
    assert "private family memory" not in json.dumps(failed)
    assert "plan" not in failed["output_manifest"]
    with SessionLocal() as db:
        row = db.get(ProductionRun, UUID(run["id"]))
        assert row.output_manifest["planning_diagnostics"][-1]["attempt"] == 3
        assert all(key.startswith(
            f"LifeReel-Biography/diagnostics/{row.tenant_id}/{row.id}/"
        ) for key in stored)
    assert len(stored) == 3
    assert "private family memory" in next(iter(stored.values()))["response"]


def test_diagnostic_storage_failure_stops_before_more_ai_calls(client, monkeypatch):
    payload = setup_pipeline(client, monkeypatch)

    class Storage:
        def put(self, key, content):
            raise RuntimeError("storage unavailable")

    monkeypatch.setattr(segmented, "private_storage", lambda: Storage())

    def invalid_plan(snapshot, subject, *, on_failure):
        on_failure({"attempt": 1, "issues": []}, {})
        pytest.fail("Must not continue without diagnostic persistence")

    monkeypatch.setattr(segmented, "plan_video", invalid_plan)
    run = client.post("/v1/production/runs", json=payload).json()
    failed = client.post(f"/v1/production/runs/{run['id']}/execute").json()
    assert failed["error_message"] == "VIDEO_PLAN_FAILED"
    assert "plan" not in failed["output_manifest"]

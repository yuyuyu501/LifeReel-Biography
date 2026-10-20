from copy import deepcopy
from uuid import uuid4

import pytest
from lifereel_api.modules.billing.models import Charge
from lifereel_api.modules.script.book_adaptation import Draft, mock_draft, validate
from lifereel_api.modules.script.models import ScriptGenerationReceipt, ScriptProject
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient
from pydantic import ValidationError
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal


def _snapshot():
    revision_id = str(uuid4())
    return {
        "revisions": [
            {
                "revision_id": revision_id,
                "title": "童年",
                "body": "我在泉州长大，小时候常在巷口玩耍。",
            }
        ],
        "subject_id": str(uuid4()),
    }


@pytest.mark.parametrize("kind", ["voiceover", "voice_over", "voice-over", "旁白", " VoiceOver "])
def test_validate_normalizes_common_narration_alias(kind):
    snapshot = _snapshot()
    result = mock_draft(snapshot, 45)
    for scene in result["scenes"]:
        scene["dialogues"][0]["kind"] = kind
    original = deepcopy(result)

    draft = validate(result, snapshot, 45)

    assert all(line.kind == "narration" for scene in draft.scenes for line in scene.dialogues)
    assert result == original
    assert Draft.model_validate(draft.model_dump(mode="json")) == draft


@pytest.mark.parametrize("kind", ["spoken-word", "monologue", "", None, True, {}, []])
def test_validate_keeps_unknown_dialogue_kind_invalid(kind):
    snapshot = _snapshot()
    result = mock_draft(snapshot, 45)
    result["scenes"][0]["dialogues"][0]["kind"] = kind

    with pytest.raises(ValidationError):
        validate(result, snapshot, 45)


def test_validate_normalizes_visual_note_list_to_text():
    snapshot = _snapshot()
    result = mock_draft(snapshot, 45)
    for scene in result["scenes"]:
        scene["visual_constraints"]["notes"] = ["保留巷口", "使用远景"]
        for shot in scene["shots"]:
            shot["visual_constraints"]["notes"] = ["避免正脸", "保持环境声"]
    original = deepcopy(result)

    draft = validate(result, snapshot, 45)

    assert all(
        scene.visual_constraints.notes == "保留巷口\n使用远景"
        for scene in draft.scenes
    )
    assert all(
        shot.visual_constraints.notes == "避免正脸\n保持环境声"
        for scene in draft.scenes
        for shot in scene.shots
    )
    assert result == original
    assert Draft.model_validate(draft.model_dump(mode="json")) == draft


@pytest.mark.parametrize("scope", ["scene", "shot"])
@pytest.mark.parametrize("notes", [["有效备注", 1], [{}], [["备注"]], {}, 1, ["a" * 500, "b"]])
def test_validate_keeps_malformed_or_overlong_notes_invalid(scope, notes):
    snapshot = _snapshot()
    result = mock_draft(snapshot, 45)
    target = result["scenes"][0]
    if scope == "shot":
        target = target["shots"][0]
    target["visual_constraints"]["notes"] = notes

    with pytest.raises(ValidationError):
        validate(result, snapshot, 45)


@pytest.mark.parametrize(
    "invalid", ["scene_source", "shot_source", "scene_duration", "shot_duration"]
)
def test_normalized_narration_still_checks_sources_and_duration(invalid):
    snapshot = _snapshot()
    result = mock_draft(snapshot, 45)
    scene = result["scenes"][0]
    scene["dialogues"][0]["kind"] = "voiceover"
    if invalid == "scene_source":
        scene["source_revision_ids"] = [str(uuid4())]
    elif invalid == "shot_source":
        scene["shots"][0]["source_revision_ids"] = [str(uuid4())]
    elif invalid == "scene_duration":
        scene["duration_seconds"] += 1
    else:
        scene["shots"][0]["duration_seconds"] += 1
    with pytest.raises(ValueError):
        validate(result, snapshot, 45)


def test_provider_aliases_are_saved_canonically_and_replay_does_not_call_model(client, monkeypatch):
    person = client.post("/v1/persons", json={"display_name": "改编测试人物"}).json()
    profile = client.get("/v1/life-profiles/subjects/" + person["id"]).json()
    updated = client.patch(
        "/v1/life-profiles/" + profile["id"],
        json={
            "expected_version": profile["version_number"],
            "request_id": str(uuid4()),
            "changes": [{
                "field_key": "work.events[]", "record_key": "synthetic",
                "value": {
                    "what": "我在工厂工作，每天整理记录并且帮助同事。" * 8,
                    "action": "主动核对记录。", "impact": "我学会了独立处理困难。",
                },
            }],
        },
    )
    assert updated.status_code == 200, updated.text
    book = client.post("/v1/books", json={"subject_id": person["id"]}).json()
    chapter = book["chapters"][0]
    saved = client.patch(
        f"/v1/books/{book['id']}/chapters/{chapter['id']}",
        json={"expected_version": 0, "title": chapter["title"],
              "body": "我在工厂工作，后来学会了独立处理困难。"},
    )
    assert saved.status_code == 200, saved.text
    revision = saved.json()["chapters"][0]["current"]
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openai-compatible")
    monkeypatch.setattr(settings, "script_llm_model", "synthetic")
    monkeypatch.setattr(settings, "openai_compatible_base_url", "https://synthetic.test/v1")
    monkeypatch.setattr(settings, "openai_compatible_api_key", "synthetic")
    calls = []

    def model(self, system, material):
        import json

        calls.append(system)
        if len(calls) == 1:
            return {"scene_plan": ["工作", "收束"]}
        data = json.loads(material)
        assert data["output_schema"] == Draft.model_json_schema()
        draft = mock_draft(data["source"], 45)
        for scene in draft["scenes"]:
            scene["dialogues"][0]["kind"] = "voiceover"
            scene["visual_constraints"] = {
                "face_policy": "no_identifiable_faces", "notes": ["避免正脸", "保留工作环境"],
            }
            for shot in scene["shots"]:
                shot["visual_constraints"] = {
                    "face_policy": "faces_allowed", "notes": ["保持自然光", "使用稳定镜头"],
                }
        return draft

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", model)
    payload = {
        "subject_id": person["id"], "book_revision_ids": [revision["id"]],
        "duration_seconds": 45, "idempotency_key": str(uuid4()),
    }
    result = client.post("/v1/scripts/generate", json=payload)
    assert result.status_code == 201, result.text
    project = result.json()
    assert all(d["kind"] == "narration" for s in project["scenes"] for d in s["dialogues"])
    assert all(s["source_claim_ids"] == [revision["id"]] for s in project["scenes"])
    assert sum(s["duration_seconds"] for s in project["scenes"]) == 45
    assert all(
        s["visual_constraints"]["notes"] == "避免正脸\n保留工作环境"
        for s in project["scenes"]
    )
    assert all(
        s["visual_constraints"]["notes"] == "避免正脸\n保留工作环境；保持自然光\n使用稳定镜头"
        and s["visual_constraints"]["face_policy"] == "no_identifiable_faces"
        for s in project["shots"]
    )
    replay = client.post("/v1/scripts/generate", json=payload).json()
    assert replay["id"] == project["id"]
    assert replay["scenes"] == project["scenes"]
    assert replay["shots"] == project["shots"]
    assert len(calls) == 2
    with SessionLocal() as db:
        assert len(list(db.scalars(select(ScriptProject)))) == 1
        receipt = db.scalar(select(ScriptGenerationReceipt))
        assert receipt.status == "completed"
        assert receipt.checkpoint["draft"]["scenes"][0]["dialogues"][0]["kind"] == "narration"
        assert receipt.checkpoint["draft"]["scenes"][0]["visual_constraints"]["notes"] == (
            "避免正脸\n保留工作环境"
        )
        assert list(db.scalars(select(Charge.status))) == ["settled"]

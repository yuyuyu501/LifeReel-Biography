from uuid import uuid4

import pytest
from test_live_interview_workflow import _start


def setup_script(client):
    person, chapter, session = _start(client)
    response = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "answer_text": "1968年，我和母亲在泉州的老屋一起做饭，这件事至今让我觉得温暖。",
            "idempotency_key": "initial-editing-test-turn",
        },
    )
    assert response.status_code == 202
    script = client.get(f"/v1/interviews/{session['id']}/workspace").json()["script"]
    return person, chapter, session, script


def edited_payload(script):
    return {
        "expected_version": script["version_number"],
        "heading": "炉边往事",
        "plot": "母女在老屋做饭。",
        "dialogues": [
            {"kind": "narration", "speaker": "林奶奶", "text": "那年我和母亲一起做饭。"},
            {"kind": "dialogue", "speaker": "母亲", "text": "慢慢来。"},
        ],
        "visual_prompt": "冬日老屋的厨房。",
        "duration_seconds": 20,
        "shots": [{"shot_type": "wide", "visual_prompt": "厨房全景", "duration_seconds": 20}],
    }


def test_regenerating_script_preserves_explicit_empty_appearance(client):
    person, chapter, _, script = setup_script(client)
    url = f"/v1/scripts/{script['id']}/scenes/{script['scenes'][0]['id']}/references"
    assert client.patch(url, json={
        "expected_version": script["version_number"], "asset_ids": [],
    }).status_code == 200
    regenerated = client.post("/v1/scripts/generate", json={
        "subject_id": person["id"], "chapter_id": chapter["id"], "mode": "single_chapter",
        "idempotency_key": str(uuid4()),
    })
    assert regenerated.status_code == 201, regenerated.text
    assert regenerated.json()["scenes"][0]["reference_asset_ids"] == []


def test_manual_edit_is_shared_free_and_leaves_production_snapshot_unchanged(client, monkeypatch):
    from lifereel_api.core.config import get_settings
    from lifereel_api.modules.jobs import service as jobs

    _, _, session, script = setup_script(client)
    scene_id = script["scenes"][0]["id"]
    monkeypatch.setattr(get_settings(), "execute_mock_jobs_inline", False)
    monkeypatch.setattr(jobs, "enqueue", lambda job: None)
    run = client.post(
        "/v1/production/runs",
        json={
            "project_id": script["id"],
            "scene_id": scene_id,
            "provider": "mock",
        },
    ).json()
    wallet = client.get("/v1/wallet").json()
    response = client.patch(
        f"/v1/scripts/{script['id']}/scenes/{scene_id}", json=edited_payload(script)
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["version_number"] == script["version_number"] + 1
    assert updated["scenes"][0]["id"] == scene_id
    assert updated["scenes"][0]["narration"] == "那年我和母亲一起做饭。\n慢慢来。"
    assert updated["scenes"][0]["plot"] == "母女在老屋做饭。"
    assert updated["shots"][0]["visual_prompt"] == "厨房全景"
    assert client.get("/v1/wallet").json() == wallet
    workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert workspace["script"]["scenes"] == updated["scenes"]
    saved_run = next(
        item for item in client.get("/v1/production/runs").json() if item["id"] == run["id"]
    )
    assert (
        saved_run["output_manifest"]["script_snapshot"] == run["output_manifest"]["script_snapshot"]
    )
    conflict = client.patch(
        f"/v1/scripts/{script['id']}/scenes/{scene_id}", json=edited_payload(script)
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "SCRIPT_EDIT_CONFLICT"


def test_invalid_edit_and_cross_tenant_access_cannot_change_script(client):
    _, _, _, script = setup_script(client)
    url = f"/v1/scripts/{script['id']}/scenes/{script['scenes'][0]['id']}"
    invalid = {**edited_payload(script), "duration_seconds": 21}
    response = client.patch(url, json=invalid)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SCRIPT_CONTENT_INVALID"
    assert (
        client.get(f"/v1/scripts/{script['id']}").json()["version_number"]
        == script["version_number"]
    )
    assert (
        client.patch(
            url, json=edited_payload(script), headers={"X-Tenant-ID": str(uuid4())}
        ).status_code
        == 404
    )


@pytest.mark.parametrize("explicit", [True, False])
def test_regeneration_request_updates_only_this_chapter_without_creating_false_memories(
    client, explicit
):
    person, _, session, script = setup_script(client)
    claims = client.get(f"/v1/memories?subject_id={person['id']}").json()
    body = {"idempotency_key": "regenerate-existing-chapter"}
    if explicit:
        body["action"] = "regenerate_script"
    else:
        body["answer_text"] = "重新生成一遍这章的剧本，旁白更自然一些。"
    url = f"/v1/interviews/{session['id']}/turns"
    response = client.post(url, json=body)
    assert response.status_code == 202
    result = response.json()
    assert result["status"] == "completed"
    assert result["script_brief"]["assessment"]["script_action"] == "regenerate_script"
    assert result["script_brief"]["assessment"]["script_updated"] is True
    assert "已重新生成" in result["next_question"]
    updated = client.get(f"/v1/scripts/{script['id']}").json()
    assert updated["version_number"] == script["version_number"] + 1
    assert len(updated["scenes"]) == 1
    assert updated["scenes"][0]["plot"]
    assert client.get(f"/v1/memories?subject_id={person['id']}").json() == claims
    assert client.post(url, json=body).json()["id"] == result["id"]
    assert (
        client.get(f"/v1/scripts/{script['id']}").json()["version_number"]
        == updated["version_number"]
    )


def test_semantic_regeneration_intent_is_taken_from_ai_not_keywords(monkeypatch):
    from lifereel_api.core.config import get_settings
    from lifereel_api.modules.orchestration.intent import classify_turn
    from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openai-compatible")
    monkeypatch.setattr(settings, "openai_compatible_base_url", "https://synthetic.test")
    monkeypatch.setattr(settings, "openai_compatible_api_key", "synthetic")
    monkeypatch.setattr(settings, "interview_llm_model", "synthetic")
    expected = {
        "action": "regenerate_script",
        "has_new_facts": False,
        "instructions": "旁白更加口语化",
    }
    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", lambda *args: expected)
    assert classify_turn("这些台词不像我说的话，能让它更像聊天的口气吗？") == expected

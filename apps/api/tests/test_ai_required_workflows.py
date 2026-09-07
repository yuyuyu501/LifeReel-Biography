from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID


def _configure_real_llm(monkeypatch) -> None:
    from lifereel_api.core.config import get_settings

    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "test-model")
    get_settings.cache_clear()


def _reset_settings() -> None:
    from lifereel_api.core.config import get_settings

    get_settings.cache_clear()


def _start_answered_interview(client, answer: str = "1968年，我和父亲林海生住在泉州。"):
    person = client.post("/v1/persons", json={"display_name": "AI 链路测试"}).json()
    chapter = client.get("/v1/chapters").json()[0]
    session = client.post(
        "/v1/interviews",
        json={"subject_id": person["id"], "chapter_id": chapter["id"]},
    ).json()
    round_ = session["rounds"][0]
    response = client.post(
        f"/v1/interviews/{session['id']}/rounds/{round_['id']}/answer",
        json={"answer_text": answer},
    )
    assert response.status_code == 200
    return person, chapter, session


def test_interview_follow_up_reports_provider_failure(client, monkeypatch) -> None:
    from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

    _, _, session = _start_answered_interview(client)
    _configure_real_llm(monkeypatch)
    monkeypatch.setattr(
        OpenAICompatibleClient,
        "chat_json",
        lambda self, system, user: (_ for _ in ()).throw(RuntimeError("provider down")),
    )
    try:
        response = client.get(f"/v1/interviews/{session['id']}/next-question")
        assert response.status_code == 502
        assert response.json() == {"error": {"code": "INTERVIEW_LLM_REQUEST_FAILED"}}
    finally:
        _reset_settings()


def test_missing_topics_are_decided_by_ai_semantics(monkeypatch) -> None:
    from lifereel_api.modules.orchestration.service import _missing_topics
    from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

    _configure_real_llm(monkeypatch)

    def semantic_gap(self, system, user):
        assert "语义判断" in system
        assert "allowed_topics" in user
        return {"missing_topics": ["当时感受"]}

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", semantic_gap)
    try:
        result = _missing_topics(
            None,
            UUID("00000000-0000-0000-0000-000000000001"),
            [SimpleNamespace(claim_text="我在泉州生活。", source_quote="我在泉州生活。")],
            [SimpleNamespace(question_text="在哪里生活？", answer_text="泉州")],
            None,
        )
        assert result == ["当时感受"]
    finally:
        _reset_settings()


def test_memory_ai_failure_rolls_back_and_interview_job_can_retry(client, monkeypatch) -> None:
    from lifereel_api.modules.jobs import service as job_service
    from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

    person = client.post("/v1/persons", json={"display_name": "重试测试"}).json()
    chapter = client.get("/v1/chapters").json()[0]
    session = client.post(
        "/v1/interviews",
        json={"subject_id": person["id"], "chapter_id": chapter["id"]},
    ).json()
    _configure_real_llm(monkeypatch)
    monkeypatch.setattr(job_service, "enqueue", lambda job: None)
    monkeypatch.setattr(
        OpenAICompatibleClient,
        "chat_json",
        lambda self, system, user: (_ for _ in ()).throw(RuntimeError("provider down")),
    )
    try:
        created = client.post(
            f"/v1/interviews/{session['id']}/turns",
            json={
                "round_id": session["rounds"][0]["id"],
                "answer_text": "1968年，我和父亲住在泉州。",
                "asset_ids": [],
                "idempotency_key": "ai-memory-retry-0001",
            },
        )
        assert created.status_code == 202
        workflow = created.json()

        executed = client.post(f"/v1/internal/interview-turns/{workflow['id']}/execute")
        assert executed.status_code == 502
        assert executed.json() == {"error": {"code": "MEMORY_LLM_REQUEST_FAILED"}}
        assert client.get(f"/v1/memories?subject_id={person['id']}").json() == []

        jobs = client.get("/v1/jobs").json()
        job = next(item for item in jobs if item["id"] == workflow["job_id"])
        assert job["status"] == "failed"
        assert job["error_code"] == "MEMORY_LLM_REQUEST_FAILED"

        duplicate_failure = client.post(
            f"/v1/jobs/{job['id']}/fail",
            json={"error_code": "WORKER_ERROR"},
        )
        assert duplicate_failure.status_code == 200
        assert duplicate_failure.json()["error_code"] == "MEMORY_LLM_REQUEST_FAILED"

        retried = client.post(f"/v1/jobs/{job['id']}/retry")
        assert retried.status_code == 200
        assert retried.json()["status"] == "queued"
        workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
        assert workspace["latest_workflow"]["status"] == "queued"
        assert workspace["latest_workflow"]["error_code"] is None
    finally:
        _reset_settings()


def test_photo_analysis_reports_vision_provider_failure(client, monkeypatch) -> None:
    from io import BytesIO

    from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

    person = client.post("/v1/persons", json={"display_name": "视觉失败测试"}).json()
    asset = client.post(
        "/v1/evidence/assets",
        data={"subject_id": person["id"], "kind": "photo"},
        files={
            "file": (
                "memory.png",
                BytesIO(b"\x89PNG\r\n\x1a\nsynthetic-image"),
                "image/png",
            )
        },
    ).json()
    _configure_real_llm(monkeypatch)
    monkeypatch.setattr(
        OpenAICompatibleClient,
        "analyze_images",
        lambda self, system, prompt, images: (_ for _ in ()).throw(
            RuntimeError("vision provider down")
        ),
    )
    try:
        response = client.post(f"/v1/evidence/assets/{asset['id']}/analyze")
        assert response.status_code == 502
        assert response.json() == {"error": {"code": "VISION_REQUEST_FAILED"}}
        observations = client.get(f"/v1/evidence/assets/{asset['id']}/observations").json()
        assert observations == []
    finally:
        _reset_settings()


def test_memory_graph_timeline_and_biography_come_from_ai(client, monkeypatch) -> None:
    from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

    person, _, session = _start_answered_interview(client)
    _configure_real_llm(monkeypatch)

    def generated(self, system, user):
        if "证据整理员" in system:
            source = json.loads(user)["source_text"]
            return {"claim_text": source, "claim_type": "relationship", "confidence": 0.96}
        if "知识图谱整理员" in system:
            claim_id = json.loads(user)["claims"][0]["claim_id"]
            return {
                "entities": [
                    {
                        "name": "林海生",
                        "normalized_name": "林海生",
                        "entity_type": "person",
                        "relationship": "父亲",
                        "source_claim_ids": [claim_id],
                    }
                ],
                "timeline": [
                    {
                        "year": 1968,
                        "time_text": "1968年",
                        "event_text": "与父亲林海生住在泉州。",
                        "precision": "year",
                        "source_claim_id": claim_id,
                    }
                ],
                "conflicts": [],
            }
        if "口述史编辑" in system:
            return {"biography": "他在1968年与父亲林海生生活在泉州。"}
        raise AssertionError(system)

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", generated)
    try:
        response = client.post(
            "/v1/memories/compile",
            json={"interview_session_id": session["id"]},
        )
        assert response.status_code == 200
        claim = response.json()["claims"][0]
        assert claim["extraction_provider"] == "openai-compatible"

        entities = client.get(f"/v1/memories/subjects/{person['id']}/entities").json()
        assert [(item["name"], item["relationship"]) for item in entities] == [("林海生", "父亲")]
        timeline = client.get(f"/v1/memories/subjects/{person['id']}/timeline").json()
        assert timeline[0]["year"] == 1968
        graph = client.get(f"/v1/memories/subjects/{person['id']}/graph").json()
        assert any(edge["relationship"] == "父亲" for edge in graph["edges"])
        refreshed_person = next(
            item for item in client.get("/v1/persons").json() if item["id"] == person["id"]
        )
        assert refreshed_person["biography_note"] == "他在1968年与父亲林海生生活在泉州。"
    finally:
        _reset_settings()


def test_real_script_rejects_response_without_ai_generated_shots(client, monkeypatch) -> None:
    from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

    person, chapter, session = _start_answered_interview(client)
    compiled = client.post(
        "/v1/memories/compile", json={"interview_session_id": session["id"]}
    ).json()
    claim_id = compiled["claims"][0]["id"]
    _configure_real_llm(monkeypatch)
    monkeypatch.setattr(
        OpenAICompatibleClient,
        "chat_json",
        lambda self, system, user: {
            "title": "测试传记",
            "chapter": {
                "heading": "第一章",
                "narration": "我和父亲住在泉州。",
                "visual_prompt": "泉州旧居。",
                "duration_seconds": 12,
                "source_claim_ids": [claim_id],
                "shots": [],
            },
        },
    )
    try:
        response = client.post(
            "/v1/scripts/generate",
            json={
                "subject_id": person["id"],
                "chapter_id": chapter["id"],
                "mode": "single_chapter",
            },
        )
        assert response.status_code == 502
        assert response.json() == {"error": {"code": "SCRIPT_LLM_RESPONSE_INVALID"}}
    finally:
        _reset_settings()

from uuid import UUID

import pytest

from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.interview.models import InterviewSession


@pytest.mark.parametrize("field", ["display_name", "is_subject", "is_minor"])
def test_person_update_rejects_explicit_null_for_required_fields(client, field):
    person = client.post("/v1/persons", json={"display_name": "边界测试人物"}).json()

    response = client.patch(f"/v1/persons/{person['id']}", json={field: None})

    assert response.status_code == 422
    unchanged = client.get(f"/v1/persons/{person['id']}").json()
    assert unchanged["display_name"] == "边界测试人物"
    assert unchanged["is_subject"] is True
    assert unchanged["is_minor"] is False


def test_person_update_distinguishes_omitted_null_and_false_values(client):
    person = client.post(
        "/v1/persons", json={
            "display_name": "可编辑人物", "preferred_name": "小名",
            "birthplace": "泉州", "is_subject": True, "is_minor": True,
        }
    ).json()

    empty = client.patch(f"/v1/persons/{person['id']}", json={})
    assert empty.status_code == 200
    for field in ("display_name", "preferred_name", "birthplace", "is_subject", "is_minor"):
        assert empty.json()[field] == person[field]

    omitted = client.patch(f"/v1/persons/{person['id']}", json={"birthplace": None})
    assert omitted.status_code == 200
    assert omitted.json()["display_name"] == "可编辑人物"
    assert omitted.json()["preferred_name"] == "小名"
    assert omitted.json()["birthplace"] is None
    assert omitted.json()["is_subject"] is True
    assert omitted.json()["is_minor"] is True

    updated = client.patch(
        f"/v1/persons/{person['id']}",
        json={"display_name": "新名字", "is_subject": False, "is_minor": False},
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "新名字"
    assert updated.json()["is_subject"] is False
    assert updated.json()["is_minor"] is False


def test_person_interview_flow(client):
    created = client.post(
        "/v1/persons",
        json={
            "display_name": "林奶奶",
            "preferred_name": "阿林",
            "birth_year": 1952,
            "birthplace": "福建泉州",
            "is_subject": True,
        },
    )
    assert created.status_code == 201
    person = created.json()

    chapters = client.get("/v1/chapters")
    assert chapters.status_code == 200
    assert len(chapters.json()) == 11

    started = client.post(
        "/v1/interviews",
        json={"subject_id": person["id"], "chapter_id": chapters.json()[2]["id"]},
    )
    assert started.status_code == 201
    session = started.json()
    assert session["status"] == "active"
    assert len(session["rounds"]) == 1

    first_round = session["rounds"][0]
    answered = client.post(
        f"/v1/interviews/{session['id']}/rounds/{first_round['id']}/answer",
        json={"answer_text": "小时候我常和妹妹去河边捡石头，母亲总在傍晚叫我们回家。"},
    )
    assert answered.status_code == 200
    assert answered.json()["transcript_status"] == "done"

    next_question = client.get(f"/v1/interviews/{session['id']}/next-question")
    assert next_question.status_code == 200
    assert next_question.json()["question_text"]

    new_round = client.post(
        f"/v1/interviews/{session['id']}/rounds",
        json=next_question.json(),
    )
    assert new_round.status_code == 201
    assert new_round.json()["round_index"] == 2

    for action in ("pause", "resume", "complete"):
        assert client.post(f"/v1/interviews/{session['id']}/{action}").status_code == 404


def test_interview_llm_receives_chapter_and_recent_answer(client, monkeypatch):
    import json

    from lifereel_api.core.config import get_settings
    from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

    person = client.post("/v1/persons", json={"display_name": "章女士"}).json()
    chapter = client.get("/v1/chapters").json()[3]
    interview = client.post(
        "/v1/interviews",
        json={"subject_id": person["id"], "chapter_id": chapter["id"]},
    ).json()
    round_ = interview["rounds"][0]
    answer = "那时我最喜欢和同学一起在图书馆看书。"
    client.post(
        f"/v1/interviews/{interview['id']}/rounds/{round_['id']}/answer",
        json={"answer_text": answer},
    )
    client.post(
        "/v1/memories/compile",
        json={"interview_session_id": interview["id"]},
    )
    other_chapter = client.get("/v1/chapters").json()[2]
    other_interview = client.post(
        "/v1/interviews",
        json={"subject_id": person["id"], "chapter_id": other_chapter["id"]},
    ).json()
    other_round = other_interview["rounds"][0]
    unrelated_answer = "童年时我常和伙伴去河边玩耍。"
    client.post(
        f"/v1/interviews/{other_interview['id']}/rounds/{other_round['id']}/answer",
        json={"answer_text": unrelated_answer},
    )
    client.post(
        "/v1/memories/compile",
        json={"interview_session_id": other_interview["id"]},
    )

    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "test-key")
    monkeypatch.setenv("INTERVIEW_LLM_MODEL", "interview-model")
    get_settings.cache_clear()

    def follow_up(self, system, user):
        context = json.loads(user)
        assert self.model == "interview-model"
        assert context["chapter"]["title"] == chapter["title"]
        assert context["chapter"]["profile"]["title"] == chapter["title"]
        assert context["chapter"]["profile"]["keywords"]
        assert context["recent_rounds"][-1]["answer"] == answer
        assert context["answered_questions"] == [round_["question_text"]]
        assert answer in context["known_memories"]
        assert unrelated_answer not in context["known_memories"]
        assert "当前唯一采访章节" in system
        assert "正确答案" in system
        return {"next_question": "图书馆里哪一本书让您印象最深？", "intent": "event"}

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", follow_up)
    try:
        response = client.get(f"/v1/interviews/{interview['id']}/next-question")
        assert response.status_code == 200
        assert response.json() == {
            "question_text": "图书馆里哪一本书让您印象最深？",
            "question_intent": "event",
            "question_source": "llm_planner",
        }
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("legacy_status", ["paused", "completed"])
def test_chapter_interview_is_reused_and_accepts_continuation(client, legacy_status):
    person = client.post("/v1/persons", json={"display_name": "周先生"}).json()
    chapter = client.get("/v1/chapters").json()[0]

    first = client.post(
        "/v1/interviews",
        json={"subject_id": person["id"], "chapter_id": chapter["id"]},
    ).json()
    first_round = first["rounds"][0]
    client.post(
        f"/v1/interviews/{first['id']}/rounds/{first_round['id']}/answer",
        json={"answer_text": "这是第一次留下的长期回答。"},
    )
    with SessionLocal() as db:
        db.get(InterviewSession, UUID(first["id"])).status = legacy_status
        db.commit()

    reused = client.post(
        "/v1/interviews",
        json={"subject_id": person["id"], "chapter_id": chapter["id"]},
    )
    assert reused.status_code == 201
    assert reused.json()["id"] == first["id"]
    assert reused.json()["rounds"][0]["answer_text"] == "这是第一次留下的长期回答。"

    continuation = {
        "answer_text": "1968年，我和母亲在泉州一起生活。",
        "idempotency_key": "legacy-continuation-001",
    }
    result = client.post(f"/v1/interviews/{first['id']}/turns", json=continuation)
    assert result.status_code == 202
    assert result.json()["status"] == "completed"
    repeated = client.post(f"/v1/interviews/{first['id']}/turns", json=continuation)
    assert repeated.json()["id"] == result.json()["id"]
    updated = client.get(f"/v1/interviews/{first['id']}").json()
    assert len(updated["rounds"]) == 3
    assert updated["rounds"][0]["answer_text"] == "这是第一次留下的长期回答。"
    assert updated["rounds"][1]["question_text"] == ""
    assert updated["rounds"][1]["answer_text"] == continuation["answer_text"]
    assert updated["rounds"][2]["answer_text"] is None

    sessions = [
        item
        for item in client.get("/v1/interviews").json()
        if item["subject_id"] == person["id"] and item["chapter_id"] == chapter["id"]
    ]
    assert len(sessions) == 1

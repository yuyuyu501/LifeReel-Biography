import json
from uuid import UUID

import pytest
from test_ai_required_workflows import (
    _configure_real_llm,
    _reset_settings,
    _start_answered_interview,
)

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.orchestration.service import _assess_chapter
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

NOT_READY = {
    "missing_topics": ["母亲当时具体做了什么", "老屋里印象最深的物件"],
    "ready_for_script": False,
    "reason": "目前只有人物称呼，还缺一件能展开的生活小事。",
}


def assess():
    return _assess_chapter(None, UUID(int=1), [], [], None)


def test_natural_language_gaps_are_normal_not_an_error(monkeypatch):
    _configure_real_llm(monkeypatch)
    calls = []

    def respond(self, system, user):
        calls.append(system)
        assert "不必逐字匹配词表" in system
        return NOT_READY

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", respond)
    try:
        assert assess() == NOT_READY
        assert len(calls) == 1
    finally:
        _reset_settings()


@pytest.mark.parametrize("invalid,issue", [
    ({}, "ASSESSMENT_TOPICS_INVALID"),
    ([], "ASSESSMENT_OBJECT_REQUIRED"),
    ({**NOT_READY, "missing_topics": "时间"}, "ASSESSMENT_TOPICS_INVALID"),
    ({**NOT_READY, "missing_topics": [None]}, "ASSESSMENT_TOPICS_INVALID"),
    ({**NOT_READY, "missing_topics": list("一二三四五")}, "ASSESSMENT_TOPICS_LIMIT"),
    ({**NOT_READY, "missing_topics": ["字" * 121]}, "ASSESSMENT_TOPICS_LIMIT"),
    ({**NOT_READY, "ready_for_script": "false"}, "ASSESSMENT_READINESS_INVALID"),
    ({**NOT_READY, "reason": " "}, "ASSESSMENT_REASON_REQUIRED"),
    (json.JSONDecodeError("invalid", "{", 0), "ASSESSMENT_JSON_INVALID"),
])
def test_invalid_assessment_is_repaired_once_before_displaying_error(monkeypatch, invalid, issue):
    _configure_real_llm(monkeypatch)
    calls = []

    def respond(self, system, user):
        calls.append(system)
        if len(calls) == 1:
            if isinstance(invalid, Exception):
                raise invalid
            return invalid
        assert issue in system
        return NOT_READY

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", respond)
    try:
        assert assess() == NOT_READY
        assert len(calls) == 2
    finally:
        _reset_settings()


def test_unrecoverable_format_failure_records_stage_and_specific_issue(monkeypatch):
    _configure_real_llm(monkeypatch)
    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", lambda *args: {})
    try:
        with pytest.raises(ApiError) as result:
            assess()
        assert result.value.code == ErrorCode.INTERVIEW_LLM_RESPONSE_INVALID
        assert result.value.diagnostic == {
            "stage": "chapter_assessment",
            "issues": ["ASSESSMENT_TOPICS_INVALID", "ASSESSMENT_TOPICS_INVALID"],
        }
    finally:
        _reset_settings()


def test_transport_failure_is_not_disguised_as_insufficient_information(monkeypatch):
    _configure_real_llm(monkeypatch)
    calls = []

    def fail(*args):
        calls.append(True)
        raise RuntimeError("connection unavailable")

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", fail)
    try:
        with pytest.raises(ApiError) as result:
            assess()
        assert result.value.code == ErrorCode.INTERVIEW_LLM_REQUEST_FAILED
        assert len(calls) == 1
    finally:
        _reset_settings()


def test_insufficient_information_is_explained_in_chat_for_an_ordinary_answer(client, monkeypatch):
    _, _, session = _start_answered_interview(client)
    _configure_real_llm(monkeypatch)
    expected = (
        "记下您和母亲住在泉州了。要写成这一章，还需要一件生活小事，"
        "您记得母亲平常怎样照顾您吗？"
    )

    def respond(self, system, user):
        assert "这就是正常采访而不是错误" in system
        assert "只提出一个具体问题" in system
        assert json.loads(user)["chapter_assessment"]["ready_for_script"] is False
        return {"next_question": expected, "intent": "event"}

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", respond)
    try:
        from lifereel_api.core.config import get_settings
        from lifereel_api.core.database import SessionLocal
        from lifereel_api.modules.interview.service import suggest_next_question

        with SessionLocal() as db:
            result = suggest_next_question(
                db, get_settings().default_tenant_id, UUID(session["id"]), assessment=NOT_READY,
            )
        assert result["question_text"] == expected
    finally:
        _reset_settings()

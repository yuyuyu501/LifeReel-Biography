from io import BytesIO
from uuid import UUID

import pytest


def test_insufficient_information_continues_interview_without_generating(client, monkeypatch):
    from lifereel_api.modules.orchestration import service
    from lifereel_api.modules.script import service as scripts

    _, _, session = _start(client)
    monkeypatch.setattr(
        service,
        "_assess_chapter",
        lambda *args: {
            "missing_topics": ["地点"],
            "ready_for_script": False,
            "reason": "仅有称呼",
        },
    )

    def unexpected(*args, **kwargs):
        raise AssertionError("Insufficient evidence must not trigger generation")

    monkeypatch.setattr(scripts, "generate_draft", unexpected)
    response = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "round_id": session["rounds"][-1]["id"],
            "answer_text": "叫我小林就好。",
            "idempotency_key": "not-ready-turn-001",
        },
    )
    assert response.status_code == 202
    workflow = response.json()
    assert workflow["status"] == "completed"
    assert workflow["error_code"] is None
    assert workflow["next_question"]
    assert workflow["script_project_id"] is None
    assert workflow["script_brief"]["assessment"]["ready_for_script"] is False
    workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert len(workspace["session"]["rounds"]) == 2
    assert workspace["session"]["rounds"][0]["answer_text"] == "叫我小林就好。"


def _start(client, name="实时采访测试"):
    person = client.post("/v1/persons", json={"display_name": name}).json()
    chapter = client.get("/v1/chapters").json()[0]
    session = client.post(
        "/v1/interviews",
        json={"subject_id": person["id"], "chapter_id": chapter["id"]},
    ).json()
    return person, chapter, session


@pytest.mark.parametrize("legacy_status", ["paused", "completed"])
def test_legacy_status_does_not_block_answering_pending_question(client, legacy_status):
    from lifereel_api.core.database import SessionLocal
    from lifereel_api.modules.interview.models import InterviewSession

    _, _, session = _start(client)
    with SessionLocal() as db:
        db.get(InterviewSession, UUID(session["id"])).status = legacy_status
        db.commit()
    response = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "answer_text": "小时候母亲教我在泉州的家里做饭。",
            "idempotency_key": "legacy-open-conversation",
        },
    )
    assert response.status_code == 202
    assert response.json()["round_id"] == session["rounds"][-1]["id"]
    assert response.json()["status"] == "completed"


def test_busy_turn_keeps_original_answer_and_does_not_create_extra_round(client, monkeypatch):
    from lifereel_api.core.config import get_settings
    from lifereel_api.modules.jobs import service as jobs

    _, _, session = _start(client)
    monkeypatch.setattr(get_settings(), "execute_mock_jobs_inline", False)
    monkeypatch.setattr(jobs, "enqueue", lambda job: None)
    response = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "round_id": session["rounds"][-1]["id"],
            "answer_text": "第一段回忆。",
            "idempotency_key": "first-queued-message",
        },
    )
    assert response.status_code == 202
    competing = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "answer_text": "另一窗口的补充。",
            "idempotency_key": "second-queued-message",
        },
    )
    assert competing.status_code == 409
    after = client.get(f"/v1/interviews/{session['id']}").json()
    assert len(after["rounds"]) == 1
    assert after["rounds"][0]["answer_text"] == "第一段回忆。"


def test_not_ready_turn_retains_previous_chapter_script(client, monkeypatch):
    from lifereel_api.modules.orchestration import service

    _, _, session = _start(client)
    response = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "round_id": session["rounds"][-1]["id"],
            "answer_text": "1968年，我和母亲在泉州的家里一起做饭。",
            "idempotency_key": "ready-original-turn",
        },
    )
    assert response.status_code == 202
    before = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    monkeypatch.setattr(
        service,
        "_assess_chapter",
        lambda *args: {
            "missing_topics": ["事情经过"],
            "ready_for_script": False,
            "reason": "需要澄清",
        },
    )
    response = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "round_id": before["session"]["rounds"][-1]["id"],
            "answer_text": "这部分我得再想想。",
            "idempotency_key": "not-ready-following-turn",
        },
    )
    assert response.status_code == 202
    assert response.json()["status"] == "completed"
    after = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert after["script"] == before["script"]
    assert len(after["session"]["rounds"]) == 3


def test_text_turn_updates_chapter_script_and_creates_next_question(client) -> None:
    person, chapter, session = _start(client)
    current = session["rounds"][-1]
    payload = {
        "round_id": current["id"],
        "answer_text": "1968年，我在泉州的学校读书，老师第一次让我在全班面前朗读。",
        "asset_ids": [],
        "idempotency_key": "live-text-turn-0001",
    }

    created = client.post(f"/v1/interviews/{session['id']}/turns", json=payload)

    assert created.status_code == 202
    workflow = created.json()
    assert workflow["status"] == "completed"
    assert workflow["script_project_id"]
    assert workflow["script_scene_ids"]
    assert workflow["next_question"]
    assert workflow["script_brief"]["chapter_id"] == chapter["id"]
    assert workflow["script_brief"]["new_facts"]
    assert client.get("/v1/wallet").json()["available_cents"] == 1998

    workspace = client.get(f"/v1/interviews/{session['id']}/workspace")
    assert workspace.status_code == 200
    body = workspace.json()
    assert body["session"]["subject_id"] == person["id"]
    assert len(body["session"]["rounds"]) == 2
    assert body["session"]["rounds"][0]["answer_text"] == payload["answer_text"]
    assert len(body["script"]["scenes"]) == 1
    assert body["script"]["scenes"][0]["chapter_id"] == chapter["id"]

    second_turn = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "round_id": body["session"]["rounds"][-1]["id"],
            "answer_text": "现在回想起来，那次朗读让我开始相信自己。",
            "asset_ids": [],
            "idempotency_key": "live-text-turn-0002",
        },
    )
    assert second_turn.status_code == 202
    updated = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert len(updated["script"]["scenes"]) == 1
    assert "现在回想起来" in updated["script"]["scenes"][0]["narration"]
    assert len(updated["script"]["scenes"][0]["source_claim_ids"]) == 2

    repeated = client.post(f"/v1/interviews/{session['id']}/turns", json=payload)
    assert repeated.status_code == 202
    assert repeated.json()["id"] == workflow["id"]
    final_workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert len(final_workspace["session"]["rounds"]) == 3
    assert client.get("/v1/wallet").json()["available_cents"] == 1996
    assert client.get("/v1/wallet/ledger?event=consume").json()["total"] == 2


@pytest.mark.parametrize("ready", [True, False])
def test_followup_retry_resumes_without_repeating_completed_ai_work(client, monkeypatch, ready):
    from lifereel_api.core.errors import ApiError, ErrorCode
    from lifereel_api.modules.interview import service as interviews
    from lifereel_api.modules.memory import service as memories
    from lifereel_api.modules.orchestration import service
    from lifereel_api.modules.script import service as scripts

    _, _, session = _start(client)
    original = interviews.suggest_next_question

    def fail(*args, **kwargs):
        raise ApiError(502, ErrorCode.INTERVIEW_LLM_REQUEST_FAILED)

    monkeypatch.setattr(
        service, "_assess_chapter",
        lambda *args: {"ready_for_script": ready, "missing_topics": [], "reason": "test"},
    )
    monkeypatch.setattr(interviews, "suggest_next_question", fail)
    response = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "round_id": session["rounds"][-1]["id"],
            "answer_text": "1968年，我出生在泉州，和父母一起生活。",
            "asset_ids": [],
            "idempotency_key": "followup-retry-test",
        },
    )
    assert response.status_code == 502
    workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert bool(workspace["script"]) is ready
    expected_balance = 1998 if ready else 2000
    assert client.get("/v1/wallet").json()["available_cents"] == expected_balance
    checkpoint = workspace["latest_workflow"]["script_brief"]
    assert checkpoint["followup_ready"] is True
    assert checkpoint["assessment"]["ready_for_script"] is ready
    before_claims = client.get(f"/v1/memories?subject_id={session['subject_id']}").json()
    monkeypatch.setattr(interviews, "suggest_next_question", original)
    monkeypatch.setattr(scripts, "generate_draft", fail)
    monkeypatch.setattr(memories, "compile_memories", fail)
    monkeypatch.setattr(service, "_assess_chapter", fail)
    workflow_id = workspace["latest_workflow"]["id"]
    monkeypatch.setattr(service.memory_recovery, "retry_after", lambda _: 0)
    result = client.post(f"/v1/internal/interview-turns/{workflow_id}/execute")
    assert result.status_code == 200
    assert result.json()["status"] == "completed"
    after = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert after["script"] == workspace["script"]
    final_brief = after["latest_workflow"]["script_brief"]
    assert {k: v for k, v in final_brief.items() if k != "memory_recovery"} == {
        k: v for k, v in checkpoint.items() if k != "memory_recovery"
    }
    assert final_brief["memory_recovery"]["runs"] == 2
    assert len(after["session"]["rounds"]) == 2
    assert after["latest_workflow"]["error_code"] is None
    assert client.get(f"/v1/memories?subject_id={session['subject_id']}").json() == before_claims
    assert client.get("/v1/wallet").json()["available_cents"] == expected_balance
    assert client.post(f"/v1/internal/interview-turns/{workflow_id}/execute").status_code == 200
    final = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert final["session"]["rounds"] == after["session"]["rounds"]


def test_document_attachment_is_linked_analyzed_and_used_by_script(client) -> None:
    person, chapter, session = _start(client, "附件采访测试")
    asset = client.post(
        "/v1/evidence/assets",
        data={
            "subject_id": person["id"],
            "interview_session_id": session["id"],
            "kind": "document",
            "consent_scope": "private",
        },
        files={
            "file": (
                "家庭记录.md",
                BytesIO("1975年，我和母亲从泉州搬到厦门。".encode()),
                "text/markdown",
            )
        },
    ).json()

    response = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "round_id": session["rounds"][-1]["id"],
            "answer_text": None,
            "asset_ids": [asset["id"]],
            "idempotency_key": "live-document-turn-0001",
        },
    )

    assert response.status_code == 202
    workflow = response.json()
    assert workflow["status"] == "completed"
    assert workflow["source_claim_ids"]
    assert workflow["script_project_id"]
    workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert [item["id"] for item in workspace["assets"]] == [asset["id"]]
    assert asset["id"] in workflow["asset_ids"]
    assert workspace["script"]["scenes"][0]["chapter_id"] == chapter["id"]


def test_turn_rejects_asset_from_another_subject(client) -> None:
    _, _, first_session = _start(client, "人物甲")
    second_person, _, _ = _start(client, "人物乙")
    foreign_asset = client.post(
        "/v1/evidence/assets",
        data={"subject_id": second_person["id"], "kind": "document"},
        files={"file": ("记录.txt", BytesIO(b"foreign"), "text/plain")},
    ).json()

    response = client.post(
        f"/v1/interviews/{first_session['id']}/turns",
        json={
            "round_id": first_session["rounds"][-1]["id"],
            "asset_ids": [foreign_asset["id"]],
            "idempotency_key": "foreign-asset-turn-0001",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "EVIDENCE_ASSET_NOT_FOUND"}}


def test_failed_script_allows_continuation_and_blocks_stale_retry(client, monkeypatch):
    from lifereel_api.core.errors import ApiError, ErrorCode
    from lifereel_api.modules.script import service as scripts

    _, _, session = _start(client)
    generate = scripts.generate_draft

    def fail(*args, **kwargs):
        raise ApiError(502, ErrorCode.SCRIPT_LLM_RESPONSE_INVALID)

    monkeypatch.setattr(scripts, "generate_draft", fail)
    response = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={"answer_text": "我叫林秀兰。", "idempotency_key": "failed-original"},
    )
    assert response.status_code == 502
    before = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    failed = before["latest_workflow"]
    assert failed["status"] == "failed"
    monkeypatch.setattr(scripts, "generate_draft", generate)
    response = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "answer_text": "现在我已经退休，和老伴住在杭州，平时喜欢写毛笔字。",
            "idempotency_key": "continue-after-failure",
        },
    )
    assert response.status_code == 202
    assert response.json()["status"] == "completed"
    after = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert after["session"]["rounds"][0]["answer_text"] == "我叫林秀兰。"
    assert "已经退休" in after["session"]["rounds"][1]["answer_text"]
    assert after["script"]
    balance = client.get("/v1/wallet").json()["available_cents"]
    retry = client.post(f"/v1/jobs/{failed['job_id']}/retry")
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "JOB_RETRY_NOT_ALLOWED"
    stale = client.post(f"/v1/internal/interview-turns/{failed['id']}/execute")
    assert stale.status_code == 409
    final = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert final["script"] == after["script"]
    assert final["session"]["rounds"] == after["session"]["rounds"]
    assert client.get("/v1/wallet").json()["available_cents"] == balance


def test_latest_failed_turn_can_retry_but_blocks_competing_submission(client, monkeypatch):
    from lifereel_api.core.errors import ApiError, ErrorCode
    from lifereel_api.modules.jobs import service as jobs
    from lifereel_api.modules.orchestration import service

    _, _, session = _start(client)
    assess = service._assess_chapter

    def fail(*args, **kwargs):
        raise ApiError(502, ErrorCode.INTERVIEW_LLM_REQUEST_FAILED)

    monkeypatch.setattr(service, "_assess_chapter", fail)
    response = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={"answer_text": "母亲教我读书。", "idempotency_key": "retry-latest"},
    )
    assert response.status_code == 502
    failed = client.get(f"/v1/interviews/{session['id']}/workspace").json()["latest_workflow"]
    monkeypatch.setattr(service.memory_recovery, "retry_after", lambda _: 0)
    monkeypatch.setattr(jobs, "enqueue", lambda job: None)
    retry = client.post(f"/v1/jobs/{failed['job_id']}/retry")
    assert retry.status_code == 200
    assert retry.json()["status"] == "queued"
    assert client.post(f"/v1/jobs/{failed['job_id']}/retry").status_code == 409
    competing = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={"answer_text": "另一段补充。", "idempotency_key": "while-retrying"},
    )
    assert competing.status_code == 409
    monkeypatch.setattr(service, "_assess_chapter", assess)
    result = client.post(f"/v1/internal/interview-turns/{failed['id']}/execute")
    assert result.status_code == 200
    assert result.json()["status"] == "completed"


def test_continuation_keeps_materials_from_failed_analysis(client, monkeypatch):
    from lifereel_api.core.errors import ApiError, ErrorCode
    from lifereel_api.modules.evidence import service as evidence

    person, _, session = _start(client)
    asset = client.post(
        "/v1/evidence/assets",
        data={
            "subject_id": person["id"],
            "interview_session_id": session["id"],
            "kind": "document",
        },
        files={"file": ("record.txt", BytesIO("母亲在杭州教我写字。".encode()), "text/plain")},
    ).json()
    analyze = evidence.analyze_asset

    def fail(*args, **kwargs):
        raise ApiError(502, ErrorCode.WORKER_ERROR)

    monkeypatch.setattr(evidence, "analyze_asset", fail)
    failed = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={"asset_ids": [asset["id"]], "idempotency_key": "failed-material"},
    )
    assert failed.status_code == 502
    monkeypatch.setattr(evidence, "analyze_asset", analyze)
    continued = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={"answer_text": "那是我童年最温暖的记忆。", "idempotency_key": "recover-material"},
    )
    assert continued.status_code == 202
    assert continued.json()["status"] == "completed"
    assert asset["id"] in continued.json()["asset_ids"]
    assert continued.json()["source_claim_ids"]
    after = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert [item["id"] for item in after["assets"]] == [asset["id"]]
    assert after["script"]

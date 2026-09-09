from io import BytesIO


def _start(client, name="实时采访测试"):
    person = client.post("/v1/persons", json={"display_name": name}).json()
    chapter = client.get("/v1/chapters").json()[0]
    session = client.post(
        "/v1/interviews",
        json={"subject_id": person["id"], "chapter_id": chapter["id"]},
    ).json()
    return person, chapter, session


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


def test_followup_retry_does_not_regenerate_or_charge_script_again(client, monkeypatch):
    from lifereel_api.core.errors import ApiError, ErrorCode
    from lifereel_api.modules.interview import service as interviews
    from lifereel_api.modules.script import service as scripts

    _, _, session = _start(client)
    original = interviews.suggest_next_question

    def fail(*args, **kwargs):
        raise ApiError(502, ErrorCode.INTERVIEW_LLM_REQUEST_FAILED)

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
    assert workspace["script"]
    assert client.get("/v1/wallet").json()["available_cents"] == 1998
    monkeypatch.setattr(interviews, "suggest_next_question", original)
    monkeypatch.setattr(scripts, "_generate_draft", fail)
    workflow_id = workspace["latest_workflow"]["id"]
    result = client.post(f"/v1/internal/interview-turns/{workflow_id}/execute")
    assert result.status_code == 200
    assert result.json()["status"] == "completed"
    after = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert after["script"]["version_number"] == workspace["script"]["version_number"]
    assert client.get("/v1/wallet").json()["available_cents"] == 1998


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

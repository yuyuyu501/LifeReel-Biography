from io import BytesIO
from uuid import uuid4

import pytest
from openpyxl import load_workbook


def profile_for(client):
    person = client.post("/v1/persons", json={"display_name": "巡检测试人物"}).json()
    return client.get("/v1/life-profiles/subjects/" + person["id"]).json()


def patch(client, profile, changes):
    response = client.patch(
        "/v1/life-profiles/" + profile["id"],
        json={
            "expected_version": profile["version_number"],
            "request_id": str(uuid4()),
            "changes": changes,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("state", ["not_applicable", "declined"])
def test_closed_relationship_branch_is_not_suggested_but_care_remains(client, state):
    profile = patch(
        client,
        profile_for(client),
        [
            {
                "field_key": "relationships.applicability",
                "value": "",
                "state": state,
            }
        ],
    )
    missing = profile["readiness"]["missing_fields"]
    assert not any(field["section"] == "F" for field in missing)
    assert any(field["section"] == "G" for field in missing)
    reopened = patch(
        client,
        profile,
        [
            {
                "field_key": "relationships.applicability",
                "value": "可以继续聊",
                "state": "filled",
            }
        ],
    )
    assert any(field["section"] == "F" for field in reopened["readiness"]["missing_fields"])


def test_export_overview_and_record_provenance_follow_selected_public_snapshot(client):
    profile = patch(
        client,
        profile_for(client),
        [
            {"field_key": "scope.coverage", "value": {"sections": ["E"]}},
            {
                "field_key": "work.events[]",
                "record_key": "one",
                "value": {
                    "title": "工作经历",
                    "what": "到工厂之后的具体工作和困难。" * 8,
                    "action": "我每天整理记录，并且主动帮助同事。",
                    "impact": "后来我学会了独立解决问题。",
                },
            },
            {"field_key": "work.meaning", "value": "禁止导出的秘密", "use_scope": "internal"},
        ],
    )
    entry = next(e for e in profile["entries"] if e["field_key"] == "work.events[]")
    path = "/v1/life-profiles/" + profile["id"] + "/export"
    response = client.get(path + "?format=xlsx&sections=E")
    assert response.status_code == 200, response.text
    workbook = load_workbook(BytesIO(response.content))
    overview = dict(workbook["说明与概况"].values)
    assert overview["人物称呼"] == "巡检测试人物"
    assert "工作、事业与生计" in overview["可写主题"]
    assert "想记录的人生范围" not in overview["仍缺内容"]
    assert "工作、事业与生计" in overview["导出类别"]
    md = client.get(path + "?format=md&sections=E").text
    assert entry["id"] in md
    assert f"条目版本：{entry['version_number']}" in md
    assert "确定性：confirmed" in md
    assert "工作、事业与生计" in md
    assert "禁止导出的秘密" not in md
    assert "禁止导出的秘密" not in str(list(workbook["资料总表"].values))


def test_saved_book_cannot_export_withdrawn_source_by_changing_directory(client):
    profile = patch(
        client,
        profile_for(client),
        [
            {
                "field_key": "work.events[]",
                "record_key": key,
                "value": {
                    "title": key,
                    "what": "我在工厂里的具体经历和工作经过。" * 8,
                    "action": "我每天主动核对记录并且帮助同事。",
                    "impact": "后来我学会了独立处理工作困难。",
                },
            }
            for key in ["one", "two"]
        ],
    )
    events = [e for e in profile["entries"] if e["field_key"] == "work.events[]"]
    response = client.post("/v1/books", json={"subject_id": profile["subject_id"]})
    assert response.status_code == 201, response.text
    book = response.json()
    chapter = book["chapters"][0]
    saved = client.patch(
        f"/v1/books/{book['id']}/chapters/{chapter['id']}",
        json={"expected_version": 0, "title": chapter["title"], "body": "包含后来撤回的私密经历。"},
    )
    assert saved.status_code == 200, saved.text
    withdrawn = events[0]
    profile = patch(
        client,
        profile,
        [
            {
                "id": withdrawn["id"],
                "field_key": withdrawn["field_key"],
                "record_key": withdrawn["record_key"],
                "value": withdrawn["value"],
                "use_scope": "internal",
            }
        ],
    )
    export_path = f"/v1/books/{book['id']}/export"
    assert client.get(export_path).status_code == 409
    directory = client.patch(
        f"/v1/books/{book['id']}/directory",
        json={
            "expected_version": book["directory_version"],
            "title": book["title"],
            "chapters": [
                {
                    "id": chapter["id"],
                    "title": chapter["title"],
                    "source_entry_ids": [events[1]["id"]],
                }
            ],
        },
    )
    assert directory.status_code == 200, directory.text
    export = client.get(export_path)
    assert export.status_code == 409, export.text
    revised = client.patch(
        f"/v1/books/{book['id']}/chapters/{chapter['id']}",
        json={
            "expected_version": 1,
            "title": chapter["title"],
            "body": "这是核对后只保留可用经历的新正文。",
            "confirm_profile_version": profile["version_number"],
        },
    )
    assert revised.status_code == 200, revised.text
    assert client.get(export_path).status_code == 200


def test_saved_book_must_apply_new_pseudonyms_before_export(client):
    profile = patch(
        client,
        profile_for(client),
        [
            {
                "field_key": "work.events[]",
                "record_key": "alias",
                "value": {
                    "title": "合作经历",
                    "what": "我和实名甲一起在工厂核对工作记录。" * 8,
                    "action": "我每天主动核对记录并且帮助实名甲。",
                    "impact": "后来我和实名甲学会了独立处理困难。",
                },
            }
        ],
    )
    event = next(e for e in profile["entries"] if e["field_key"] == "work.events[]")
    book = client.post("/v1/books", json={"subject_id": profile["subject_id"]}).json()
    chapter = book["chapters"][0]
    path = f"/v1/books/{book['id']}/chapters/{chapter['id']}"
    saved = client.patch(
        path,
        json={
            "expected_version": 0,
            "title": chapter["title"],
            "body": "我和实名甲一起工作。",
        },
    )
    assert saved.status_code == 200, saved.text
    profile = patch(
        client,
        profile,
        [
            {
                "id": event["id"],
                "field_key": event["field_key"],
                "record_key": event["record_key"],
                "value": event["value"],
                "use_scope": "pseudonym",
                "pseudonyms": {"实名甲": "同事甲"},
            }
        ],
    )
    export_path = f"/v1/books/{book['id']}/export"
    assert client.get(export_path).status_code == 409
    revised = client.patch(
        path,
        json={
            "expected_version": 1,
            "title": chapter["title"],
            "body": "我和同事甲一起工作。",
            "confirm_profile_version": profile["version_number"],
        },
    )
    assert revised.status_code == 200, revised.text
    exported = client.get(export_path)
    assert exported.status_code == 200, exported.text
    assert "同事甲" in exported.text and "实名甲" not in exported.text


def test_book_adaptation_copies_scene_constraints_to_every_shot(client, monkeypatch):
    from lifereel_api.modules.script import book_adaptation

    profile = patch(
        client,
        profile_for(client),
        [
            {
                "field_key": "work.events[]",
                "record_key": "visual",
                "value": {
                    "what": "我在工厂的具体工作经历和每天发生的事情。" * 8,
                    "action": "我每天主动核对记录并且帮助同事。",
                    "impact": "后来我学会了独立处理工作困难。",
                },
            }
        ],
    )
    book = client.post("/v1/books", json={"subject_id": profile["subject_id"]}).json()
    chapter = book["chapters"][0]
    saved = client.patch(
        f"/v1/books/{book['id']}/chapters/{chapter['id']}",
        json={
            "expected_version": 0,
            "title": chapter["title"],
            "body": "我到工厂工作，后来学会了独立处理困难。",
        },
    )
    assert saved.status_code == 200, saved.text
    revision = saved.json()["chapters"][0]["current"]
    mock_draft = book_adaptation.mock_draft

    def draft_with_scene_restrictions(snapshot, duration):
        draft = mock_draft(snapshot, duration)
        for scene in draft["scenes"]:
            scene["visual_constraints"] = {
                "face_policy": "no_identifiable_faces",
                "required_elements": ["工厂门口"],
                "forbidden_elements": ["现代广告牌"],
            }
            for shot in scene["shots"]:
                shot["visual_constraints"] = {"face_policy": "faces_allowed"}
        return draft

    monkeypatch.setattr(book_adaptation, "mock_draft", draft_with_scene_restrictions)
    response = client.post(
        "/v1/scripts/generate",
        json={
            "subject_id": profile["subject_id"],
            "book_revision_ids": [revision["id"]],
            "duration_seconds": 45,
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert sum(s["duration_seconds"] for s in result["scenes"]) == 45
    for shot in result["shots"]:
        assert 4 <= shot["duration_seconds"] <= 10
        constraints = shot["visual_constraints"]
        assert constraints["face_policy"] == "no_identifiable_faces"
        assert "工厂门口" in constraints["required_elements"]
        assert "现代广告牌" in constraints["forbidden_elements"]

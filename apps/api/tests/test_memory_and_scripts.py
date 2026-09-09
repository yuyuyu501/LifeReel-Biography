from io import BytesIO


def test_compile_memories_and_generate_traceable_script(client) -> None:
    person = client.post("/v1/persons", json={"display_name": "林秀兰"}).json()
    chapter = client.get("/v1/chapters").json()[2]
    interview = client.post(
        "/v1/interviews",
        json={"subject_id": person["id"], "chapter_id": chapter["id"]},
    ).json()
    first_round = interview["rounds"][0]
    answer = "小时候我常和姐姐去村口的榕树下等父亲收工，雨天也会去。"
    client.post(
        f"/v1/interviews/{interview['id']}/rounds/{first_round['id']}/answer",
        json={"answer_text": answer},
    )

    compiled = client.post(
        "/v1/memories/compile", json={"interview_session_id": interview["id"]}
    )
    assert compiled.status_code == 200
    claim = compiled.json()["claims"][0]
    assert claim["source_round_id"] == first_round["id"]
    assert claim["source_quote"] == answer

    overview = client.get(f"/v1/memories/subjects/{person['id']}/overview").json()
    assert overview["claim_count"] == 1
    assert overview["coverage_ratio"] > 0
    entities = client.get(f"/v1/memories/subjects/{person['id']}/entities").json()
    assert any(item["name"] == "姐姐" for item in entities)
    timeline = client.get(f"/v1/memories/subjects/{person['id']}/timeline").json()
    assert timeline[0]["time_text"] == "小时候"

    graph_response = client.get(f"/v1/memories/subjects/{person['id']}/graph")
    assert graph_response.status_code == 200
    graph = graph_response.json()
    subject_node = next(node for node in graph["nodes"] if node["kind"] == "subject")
    sister_node = next(node for node in graph["nodes"] if node["label"] == "姐姐")
    father_node = next(node for node in graph["nodes"] if node["label"] == "父亲")
    village_node = next(node for node in graph["nodes"] if node["label"] == "村口")
    event_node = next(node for node in graph["nodes"] if node["kind"] == "event")
    relationships = {edge["target_id"]: edge for edge in graph["edges"]}
    assert subject_node["label"] == "林秀兰"
    assert answer in (subject_node["description"] or "")
    assert relationships[sister_node["id"]]["relationship"] == "姐姐"
    assert relationships[father_node["id"]]["relationship"] == "父亲"
    assert relationships[village_node["id"]]["relationship"] == "生活地点"
    assert event_node["time_text"] == "小时候"
    assert claim["id"] in event_node["source_claim_ids"]
    assert claim["id"] in relationships[sister_node["id"]]["source_claim_ids"]

    reviewed = client.patch(
        f"/v1/memories/{claim['id']}/review", json={"status": "verified"}
    )
    assert reviewed.json()["review_status"] == "verified"

    duplicate_compile = client.post(
        "/v1/memories/compile", json={"interview_session_id": interview["id"]}
    ).json()
    assert duplicate_compile["created_count"] == 0
    assert duplicate_compile["existing_count"] == 1

    script = client.post(
        "/v1/scripts/generate",
        json={
            "subject_id": person["id"],
            "chapter_id": chapter["id"],
            "mode": "single_chapter",
            "audience": "family",
        },
    )
    assert script.status_code == 201
    payload = script.json()
    assert "review_status" not in payload
    assert "locked_at" not in payload
    assert payload["scenes"][0]["source_claim_ids"] == [claim["id"]]
    assert answer in payload["scenes"][0]["narration"]

    removed_review = client.post(
        f"/v1/scripts/{payload['id']}/review", json={"status": "approved"}
    )
    assert removed_review.status_code == 404
    assert removed_review.json()["error"]["code"] == "ROUTE_NOT_FOUND"


def test_one_active_script_is_continuously_regenerated(client) -> None:
    person = client.post("/v1/persons", json={"display_name": "章节更新测试"}).json()
    chapters = client.get("/v1/chapters").json()[:2]
    for chapter, answer in zip(
        chapters,
        ["小时候我每天沿着河边上学。", "工作以后我在车间负责设备检修。"],
        strict=True,
    ):
        interview = client.post(
            "/v1/interviews",
            json={"subject_id": person["id"], "chapter_id": chapter["id"]},
        ).json()
        first_round = interview["rounds"][0]
        client.post(
            f"/v1/interviews/{interview['id']}/rounds/{first_round['id']}/answer",
            json={"answer_text": answer},
        )
        client.post(
            "/v1/memories/compile", json={"interview_session_id": interview["id"]}
        )

    first = client.post(
        "/v1/scripts/generate",
        json={"subject_id": person["id"], "mode": "multi_chapter"},
    ).json()
    second = client.post(
        "/v1/scripts/generate",
        json={"subject_id": person["id"], "mode": "multi_chapter"},
    ).json()
    assert second["id"] == first["id"]
    assert second["version_number"] == 2
    assert len(client.get("/v1/scripts").json()) == 1
    assert len(second["scenes"]) == 2
    assert {scene["chapter_id"] for scene in second["scenes"]} == {
        chapter["id"] for chapter in chapters
    }

    assert all("review_status" not in scene for scene in second["scenes"])
    production = client.post(
        "/v1/production/runs",
        json={"project_id": second["id"], "audience": "family", "provider": "mock"},
    )
    assert production.status_code == 201
    assert production.json()["status"] == "completed"


def test_document_observation_compiles_into_traceable_memory(client) -> None:
    person = client.post("/v1/persons", json={"display_name": "素材主人公"}).json()
    asset = client.post(
        "/v1/evidence/assets",
        data={"subject_id": person["id"], "kind": "document"},
        files={
            "file": (
                "家庭记录.md",
                BytesIO("1968年，我第一次离开家乡去读书。".encode()),
                "text/markdown",
            )
        },
    ).json()

    observation = client.post(f"/v1/evidence/assets/{asset['id']}/analyze")
    assert observation.status_code == 200
    observation_payload = observation.json()
    assert observation_payload["analysis_kind"] == "document_text"
    assert observation_payload["provider"] == "local"

    compiled = client.post("/v1/memories/compile", json={"subject_id": person["id"]})
    assert compiled.status_code == 200
    claim = compiled.json()["claims"][0]
    assert claim["source_round_id"] is None
    assert claim["source_observation_id"] == observation_payload["id"]
    assert "1968年" in claim["claim_text"]


def test_compile_merges_repeated_entities_within_one_transaction(client) -> None:
    person = client.post("/v1/persons", json={"display_name": "重复实体测试"}).json()
    interviews = [
        client.post("/v1/interviews", json={"subject_id": person["id"]}).json()
        for _ in range(2)
    ]
    for index, interview in enumerate(interviews):
        first_round = interview["rounds"][0]
        response = client.post(
            f"/v1/interviews/{interview['id']}/rounds/{first_round['id']}/answer",
            json={"answer_text": f"第{index + 1}段回忆里，我都提到了外婆。"},
        )
        assert response.status_code == 200

    compiled = client.post("/v1/memories/compile", json={"subject_id": person["id"]})
    assert compiled.status_code == 200
    assert compiled.json()["created_count"] == 2

    entities = client.get(f"/v1/memories/subjects/{person['id']}/entities").json()
    matching = [entity for entity in entities if entity["name"] == "外婆"]
    assert len(matching) == 1
    assert len(matching[0]["source_claim_ids"]) == 2


def test_memory_graph_excludes_private_and_disputed_claims(client) -> None:
    person = client.post("/v1/persons", json={"display_name": "图谱隐私测试"}).json()
    claims = []
    for answer in ("小时候我常和姐姐去村口。", "后来父亲带我去了工厂。"):
        interview = client.post("/v1/interviews", json={"subject_id": person["id"]}).json()
        first_round = interview["rounds"][0]
        client.post(
            f"/v1/interviews/{interview['id']}/rounds/{first_round['id']}/answer",
            json={"answer_text": answer},
        )
        claims.append(
            client.post(
                "/v1/memories/compile", json={"interview_session_id": interview["id"]}
            ).json()["claims"][-1]
        )

    private_review = client.patch(
        f"/v1/memories/{claims[0]['id']}/review", json={"status": "private"}
    )
    disputed_review = client.patch(
        f"/v1/memories/{claims[1]['id']}/review", json={"status": "disputed"}
    )
    assert private_review.json()["review_status"] == "private"
    assert disputed_review.json()["review_status"] == "disputed"
    graph = client.get(f"/v1/memories/subjects/{person['id']}/graph").json()
    assert [node["kind"] for node in graph["nodes"]] == ["subject"]
    assert graph["edges"] == []

    missing = client.get("/v1/memories/subjects/00000000-0000-0000-0000-000000000001/graph")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "SUBJECT_NOT_FOUND"


def test_birth_year_conflicts_ignore_a_childs_birth_year(client) -> None:
    person = client.post("/v1/persons", json={"display_name": "出生年份测试"}).json()
    answers = [
        "我于1965年出生在宁波。",
        "1992年孩子出生后，我开始更珍惜与家人相处的时间。",
    ]
    for answer in answers:
        interview = client.post("/v1/interviews", json={"subject_id": person["id"]}).json()
        first_round = interview["rounds"][0]
        response = client.post(
            f"/v1/interviews/{interview['id']}/rounds/{first_round['id']}/answer",
            json={"answer_text": answer},
        )
        assert response.status_code == 200

    compiled = client.post("/v1/memories/compile", json={"subject_id": person["id"]})
    assert compiled.status_code == 200
    conflicts = client.get(f"/v1/memories/subjects/{person['id']}/conflicts").json()
    assert conflicts == []


def test_openai_compatible_script_uses_structured_evidence_references(
    client, monkeypatch
) -> None:
    from lifereel_api.core.config import get_settings
    from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

    person = client.post("/v1/persons", json={"display_name": "顾先生"}).json()
    interview = client.post("/v1/interviews", json={"subject_id": person["id"]}).json()
    round_ = interview["rounds"][0]
    client.post(
        f"/v1/interviews/{interview['id']}/rounds/{round_['id']}/answer",
        json={"answer_text": "我年轻时在码头工作，每天清晨听着船笛上班。"},
    )
    claim = client.post(
        "/v1/memories/compile", json={"interview_session_id": interview["id"]}
    ).json()["claims"][0]

    second_interview = client.post(
        "/v1/interviews", json={"subject_id": person["id"]}
    ).json()
    second_round = second_interview["rounds"][0]
    client.post(
        f"/v1/interviews/{second_interview['id']}/rounds/{second_round['id']}/answer",
        json={"answer_text": "后来我开始负责整理码头的工作记录。"},
    )
    second_claim = next(
        item
        for item in client.post(
            "/v1/memories/compile", json={"interview_session_id": second_interview["id"]}
        ).json()["claims"]
        if item["source_round_id"] == second_round["id"]
    )

    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "test-key")
    monkeypatch.setenv("SCRIPT_LLM_MODEL", "script-model")
    get_settings.cache_clear()

    def generated(self, system, user):
        assert self.model == "script-model"
        assert claim["id"] in user
        assert "一份完整、连续的当前章节稿件" in system
        return {
            "title": "船笛响起的清晨",
            "chapter": {
                "heading": "码头清晨",
                "narration": "我年轻时在码头工作，每天伴着船笛开始一天。",
                "visual_prompt": "清晨的旧码头，不出现未经授权的正脸。",
                "duration_seconds": 12,
                "source_claim_ids": [claim["id"], "00000000-0000-0000-0000-000000000099"],
                "shots": [
                    {
                        "shot_type": "wide",
                        "visual_prompt": "码头环境建立镜头。",
                        "duration_seconds": 6,
                        "source_claim_ids": [
                            second_claim["id"],
                            "00000000-0000-0000-0000-000000000098",
                        ],
                    }
                ],
            },
        }

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", generated)
    try:
        response = client.post(
            "/v1/scripts/generate",
            json={"subject_id": person["id"], "mode": "single_chapter"},
        )
        assert response.status_code == 201
        script = response.json()
        assert script["title"] == "船笛响起的清晨"
        assert script["generation_provider"] == "openai-compatible"
        assert script["generation_model"] == "script-model"
        assert script["scenes"][0]["source_claim_ids"] == [claim["id"], second_claim["id"]]
        assert script["shots"][0]["source_claim_ids"] == [second_claim["id"]]
        assert sum(shot["duration_seconds"] for shot in script["shots"]) == sum(
            scene["duration_seconds"] for scene in script["scenes"]
        )
    finally:
        get_settings.cache_clear()

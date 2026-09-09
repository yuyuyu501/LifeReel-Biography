import pytest


@pytest.mark.parametrize("is_minor", [False, True])
def test_production_without_consent_and_separate_publication(client, is_minor) -> None:
    person = client.post(
        "/v1/persons", json={"display_name": "陈阿姨", "is_minor": is_minor}
    ).json()
    chapter = client.get("/v1/chapters").json()[0]
    interview = client.post(
        "/v1/interviews",
        json={"subject_id": person["id"], "chapter_id": chapter["id"]},
    ).json()
    round_ = interview["rounds"][0]
    client.post(
        f"/v1/interviews/{interview['id']}/rounds/{round_['id']}/answer",
        json={"answer_text": "我出生在1958年，家乡在苏州，母亲很会唱评弹。"},
    )
    client.post("/v1/memories/compile", json={"interview_session_id": interview["id"]})
    script = client.post(
        "/v1/scripts/generate",
        json={"subject_id": person["id"], "mode": "single_chapter", "audience": "family"},
    ).json()

    production = client.post(
        "/v1/production/runs",
        json={"project_id": script["id"], "audience": "family", "provider": "mock"},
    )
    assert production.status_code == 201
    run = production.json()
    assert run["status"] == "completed"
    assert run["job_id"]
    assert run["assets"][0]["mime_type"] in {"video/mp4", "application/json"}
    assert run["output_manifest"]["asset_id"] == run["assets"][0]["id"]
    assert run["error_message"] is None
    generated = client.get(f"/v1/production/assets/{run['assets'][0]['id']}/content")
    assert generated.status_code == 200
    assert generated.content
    jobs = client.get("/v1/jobs").json()
    assert jobs[0]["status"] == "completed"
    duplicate = client.post(
        "/v1/production/runs",
        json={"project_id": script["id"], "audience": "family", "provider": "mock"},
    ).json()
    assert duplicate["id"] == run["id"]
    invalid_provider = client.post(
        "/v1/production/runs",
        json={"project_id": script["id"], "audience": "family", "provider": "unknown"},
    )
    assert invalid_provider.status_code == 422

    mismatched_audience = client.post(
        "/v1/publications",
        json={"production_run_id": run["id"], "audience": "public"},
    )
    assert mismatched_audience.status_code == 409

    publication = client.post(
        "/v1/publications",
        json={"production_run_id": run["id"], "audience": "family"},
    )
    assert publication.status_code == 409
    assert publication.json()["error"]["code"] == "PUBLICATION_CONSENT_REQUIRED"
    consent = client.post("/v1/consents", json={
        "subject_id": person["id"], "consent_type": "publication", "scope": "family",
        "granted_by": "陈阿姨本人", "evidence_note": "测试环境书面确认",
    })
    assert consent.status_code == 201
    publication = client.post(
        "/v1/publications", json={"production_run_id": run["id"], "audience": "family"}
    )
    assert publication.status_code == 201
    published = publication.json()
    public_lookup = client.get(f"/v1/public/{published['access_token']}")
    assert public_lookup.status_code == 200
    assert "access_token" not in public_lookup.json()
    public_content = client.get(f"/v1/public/{published['access_token']}/content")
    assert public_content.status_code == 200
    assert public_content.content

    withdrawn = client.post(f"/v1/publications/{published['id']}/withdraw")
    assert withdrawn.json()["status"] == "withdrawn"
    assert client.get(f"/v1/public/{published['access_token']}").status_code == 404
    assert client.get(f"/v1/public/{published['access_token']}/content").status_code == 404
    assert len(client.get("/v1/audit").json()) >= 3

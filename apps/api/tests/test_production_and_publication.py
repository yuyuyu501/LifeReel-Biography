import pytest


@pytest.mark.parametrize("is_minor", [False, True])
def test_production_without_consent_and_separate_publication(client, is_minor) -> None:
    person = client.post(
        "/v1/persons", json={"display_name": "陈阿姨", "is_minor": is_minor}
    ).json()
    chapter = client.get("/v1/chapters").json()[0]
    interview = client.post(
        "/v1/interviews",
        json={"mode": "legacy", "subject_id": person["id"], "chapter_id": chapter["id"]},
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
    consent = client.post(
        "/v1/consents",
        json={
            "subject_id": person["id"],
            "consent_type": "publication",
            "scope": "family",
            "granted_by": "陈阿姨本人",
            "evidence_note": "测试环境书面确认",
        },
    )
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
    assert public_content.headers["cache-control"] == "no-store"
    assert public_lookup.headers["cache-control"] == "no-store"

    withdrawn = client.post(f"/v1/publications/{published['id']}/withdraw")
    assert withdrawn.json()["status"] == "withdrawn"
    assert client.get(f"/v1/public/{published['access_token']}").status_code == 404
    assert client.get(f"/v1/public/{published['access_token']}/content").status_code == 404
    assert len(client.get("/v1/audit").json()) >= 3


@pytest.fixture
def authorized_publication(client):
    from uuid import UUID

    from lifereel_api.modules.production.models import ProductionRun
    from lifereel_api.modules.script.models import ScriptProject

    from lifereel_api.core.database import SessionLocal

    person = client.post("/v1/persons", json={"display_name": "授权测试人物"}).json()
    # An existing completed run is sufficient; no paid generation is involved.
    with SessionLocal() as db:
        from lifereel_api.modules.identity.models import Person

        subject = db.get(Person, UUID(person["id"]))
        project = ScriptProject(
            tenant_id=subject.tenant_id,
            subject_id=subject.id,
            title="测试影像",
            mode="single_chapter",
            audience="family",
            status="ready",
        )
        db.add(project)
        db.flush()
        run = ProductionRun(
            tenant_id=subject.tenant_id,
            project_id=project.id,
            audience="family",
            provider="mock",
            status="completed",
        )
        db.add(run)
        db.commit()
        run_id = str(run.id)
    grant_payload = {
        "subject_id": person["id"],
        "consent_type": "publication",
        "scope": "family",
        "granted_by": "本人",
    }
    grant = client.post("/v1/consents", json=grant_payload)
    assert grant.status_code == 201, grant.text
    payload = {"production_run_id": run_id, "audience": "family"}
    publication = client.post("/v1/publications", json=payload)
    assert publication.status_code == 201, publication.text
    return grant.json(), grant_payload, publication.json(), payload


@pytest.mark.parametrize("reason", ["revoked", "expired"])
def test_publication_loses_access_when_consent_ends(client, authorized_publication, reason):
    from datetime import UTC, datetime, timedelta
    from uuid import UUID

    from lifereel_api.modules.governance.models import ConsentGrant

    from lifereel_api.core.database import SessionLocal

    grant, _, publication, _ = authorized_publication
    path = f"/v1/public/{publication['access_token']}"
    assert client.get(path).status_code == 200
    if reason == "revoked":
        assert client.post(f"/v1/consents/{grant['id']}/revoke").status_code == 200
    else:
        with SessionLocal() as db:
            db.get(ConsentGrant, UUID(grant["id"])).expires_at = datetime.now(UTC) - timedelta(
                seconds=1
            )
            db.commit()
    assert client.get(path).status_code == 404
    assert client.get(path + "/content").status_code == 404
    assert client.get("/v1/publications").json()[0]["status"] == "withdrawn"


def test_new_consent_cannot_resurrect_unvisited_old_link(client, authorized_publication):
    grant, grant_payload, publication, payload = authorized_publication
    client.post(f"/v1/consents/{grant['id']}/revoke")
    assert client.post("/v1/consents", json=grant_payload).status_code == 201
    path = f"/v1/public/{publication['access_token']}"
    assert client.get(path).status_code == 404
    new = client.post("/v1/publications", json=payload)
    assert new.status_code == 201
    assert new.json()["access_token"] != publication["access_token"]
    assert client.get(f"/v1/public/{new.json()['access_token']}").status_code == 200


def test_another_preexisting_consent_can_still_cover_a_link(client, authorized_publication):
    grant, grant_payload, _, payload = authorized_publication
    second = client.post("/v1/consents", json=grant_payload).json()
    publication = client.post("/v1/publications", json=payload).json()
    client.post(f"/v1/consents/{grant['id']}/revoke")
    path = f"/v1/public/{publication['access_token']}"
    assert client.get(path).status_code == 200
    client.post(f"/v1/consents/{second['id']}/revoke")
    # Listing synchronizes the stored status even before anyone opens the link.
    assert all(item["status"] == "withdrawn" for item in client.get("/v1/publications").json())
    assert client.get(path).status_code == 404

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

    # Playback stays available to the owner without a publication grant.
    for audience in ("private", "family", "friends", "public"):
        response = client.post(
            "/v1/publications",
            json={"production_run_id": run["id"], "audience": audience},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PUBLICATION_UNAVAILABLE"


@pytest.mark.parametrize("audience", ["private", "family", "friends", "public"])
def test_legacy_tokens_never_expose_metadata_or_content(client, audience):
    from datetime import UTC, datetime
    from uuid import UUID

    from lifereel_api.modules.identity.models import Person
    from lifereel_api.modules.production.models import ProductionRun
    from lifereel_api.modules.publication import service
    from lifereel_api.modules.publication.models import Publication
    from lifereel_api.modules.script.models import ScriptProject

    from lifereel_api.core.database import SessionLocal
    from lifereel_api.core.errors import ApiError

    person = client.post("/v1/persons", json={"display_name": "私密测试人物"}).json()
    with SessionLocal() as db:
        subject = db.get(Person, UUID(person["id"]))
        project = ScriptProject(
            tenant_id=subject.tenant_id, subject_id=subject.id,
            title="私密影像", mode="single_chapter", audience=audience, status="ready",
        )
        db.add(project)
        db.flush()
        run = ProductionRun(
            tenant_id=subject.tenant_id, project_id=project.id,
            audience=audience, provider="mock", status="completed",
        )
        db.add(run)
        db.flush()
        publication = Publication(
            tenant_id=subject.tenant_id, subject_id=subject.id,
            production_run_id=run.id, audience=audience,
            status="published", access_token="legacy-token", published_at=datetime.now(UTC),
        )
        db.add(publication)
        db.commit()
        for lookup in (service.public_lookup, service.public_asset):
            with pytest.raises(ApiError) as exc:
                lookup(db, "legacy-token")
            assert exc.value.status_code == 404
    for suffix in ("", "/content"):
        response = client.get("/v1/public/legacy-token" + suffix)
        assert response.status_code == 404
        assert not response.content
        assert response.headers["cache-control"] == "no-store"
    # Even a valid grant cannot enable new publishing or revive a legacy token.
    assert client.post("/v1/consents", json={
        "subject_id": person["id"], "consent_type": "publication",
        "scope": "public", "granted_by": "本人",
    }).status_code == 201
    assert client.get("/v1/public/legacy-token").status_code == 404
    assert client.post("/v1/publications", json={
        "production_run_id": str(run.id), "audience": audience,
    }).status_code == 409


def test_production_public_paths_no_longer_bypass_authentication(client, monkeypatch):
    from lifereel_api.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "api_access_key", "synthetic-private-key")
    for path in ("/v1/public/legacy-token", "/v1/public/legacy-token/content", "/v1/books"):
        assert client.get(path).status_code == 401
        # The internal gateway key by itself is not a signed user session.
        assert client.get(path, headers={"X-API-Key": "synthetic-private-key"}).status_code == 401

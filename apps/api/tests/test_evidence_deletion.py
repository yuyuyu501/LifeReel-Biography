from io import BytesIO
from uuid import UUID, uuid4

import pytest
from lifereel_api.modules.evidence.models import SourceAsset, Transcript
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal


def upload(client, mime="text/plain"):
    person = client.post("/v1/persons", json={"display_name": "合成素材测试"}).json()
    response = client.post(
        "/v1/evidence/assets",
        data={"subject_id": person["id"], "kind": "document"},
        files={"file": ("memoir.txt", BytesIO("1970年出生，1988年毕业。".encode()), mime)},
    )
    assert response.status_code == 201, response.text
    return person, response.json()


@pytest.mark.parametrize("mime", ["text/plain", "application/octet-stream"])
def test_txt_upload_delete_and_reupload(client, mime):
    person, asset = upload(client, mime)
    url = f"/v1/evidence/assets/{asset['id']}"
    assert client.get(url + "/content").status_code == 200
    assert client.delete(url).status_code == 204
    assert client.get("/v1/evidence/assets", params={"subject_id": person["id"]}).json() == []
    assert client.get(url + "/content").status_code == 404
    assert client.delete(url).status_code == 404
    # Retained storage blobs must not prevent a fresh upload of the same bytes.
    response = client.post(
        "/v1/evidence/assets",
        data={"subject_id": person["id"], "kind": "document"},
        files={"file": ("memoir.txt", BytesIO("1970年出生，1988年毕业。".encode()), mime)},
    )
    assert response.status_code == 201, response.text
    assert response.json()["id"] != asset["id"]


def test_cannot_delete_other_tenant_asset(client):
    _, asset = upload(client)
    url = f"/v1/evidence/assets/{asset['id']}"
    assert client.delete(url, headers={"X-Tenant-ID": str(uuid4())}).status_code == 404
    assert client.get(url + "/content").status_code == 200


def test_transcript_source_is_preserved(client):
    _, asset = upload(client)
    with SessionLocal() as db:
        db.add(
            Transcript(
                tenant_id=get_settings().default_tenant_id, source_asset_id=UUID(asset["id"])
            )
        )
        db.commit()
    url = f"/v1/evidence/assets/{asset['id']}"
    response = client.delete(url)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "EVIDENCE_ASSET_IN_USE"
    assert client.get(url + "/content").status_code == 200


def link_material(client, person, asset, *, repeats=1):
    profile = client.get("/v1/life-profiles/subjects/" + person["id"]).json()
    response = client.patch(
        "/v1/life-profiles/" + profile["id"],
        json={
            "expected_version": profile["version_number"],
            "request_id": str(uuid4()),
            "changes": [
                {
                    "field_key": "materials.assets[]",
                    "record_key": "material-" + str(i),
                    "value": {"asset_id": asset["id"], "title": "合成资料"},
                }
                for i in range(repeats)
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("repeats", [1, 2])
def test_delete_unlinks_saved_material_and_updates_profile_history(client, repeats):
    from lifereel_api.modules.interview.profile_models import LifeProfileRevision
    from lifereel_api.modules.interview.profile_service import sync_memory
    from lifereel_api.modules.jobs.events import OutboxEvent
    from lifereel_api.modules.memory.models import MemoryClaim

    person, asset = upload(client)
    profile = link_material(client, person, asset, repeats=repeats)
    other_person = client.post("/v1/persons", json={"display_name": "另一个合成人物"}).json()
    other_profile = client.get("/v1/life-profiles/subjects/" + other_person["id"]).json()
    url = f"/v1/evidence/assets/{asset['id']}"
    assert client.delete(url).status_code == 204
    assert client.get(url + "/content").status_code == 404
    assert client.get("/v1/evidence/assets", params={"subject_id": person["id"]}).json() == []
    updated = client.get("/v1/life-profiles/" + profile["id"]).json()
    assert updated["version_number"] == profile["version_number"] + 1
    assert updated["readiness"]["profile_version"] == updated["version_number"]
    materials = [e for e in updated["entries"] if e["field_key"] == "materials.assets[]"]
    assert len(materials) == repeats
    assert all(e["state"] == "empty" and e["value"] == "" for e in materials)
    assert client.get("/v1/life-profiles/" + other_profile["id"]).json() == other_profile
    with SessionLocal() as db:
        revision = db.scalar(
            select(LifeProfileRevision).where(
                LifeProfileRevision.profile_id == UUID(profile["id"]),
                LifeProfileRevision.version_number == updated["version_number"],
            )
        )
        assert revision.actor == "manual:asset-delete"
        assert len(revision.changes) == repeats
        assert all(c["after"] is None for c in revision.changes)
        assert (
            db.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == "profile.sync.requested",
                    OutboxEvent.aggregate_id == UUID(profile["id"]),
                    OutboxEvent.payload["version"].as_integer() == updated["version_number"],
                )
            )
            is not None
        )
        sync_memory(db, get_settings().default_tenant_id, UUID(profile["id"]))
        claims = list(
            db.scalars(
                select(MemoryClaim).where(
                    MemoryClaim.profile_entry_id.in_([UUID(e["id"]) for e in materials]),
                )
            )
        )
        assert len(claims) == repeats
        assert all(c.review_status == "superseded" for c in claims)
    # A stale editor must not restore the removed link after the profile version changed.
    stale = client.patch(
        "/v1/life-profiles/" + profile["id"],
        json={
            "expected_version": profile["version_number"],
            "request_id": str(uuid4()),
            "changes": [
                {
                    "field_key": "materials.assets[]",
                    "record_key": "material-0",
                    "value": {"asset_id": asset["id"]},
                }
            ],
        },
    )
    assert stale.status_code == 409


def test_protected_source_does_not_partially_unlink_profile(client):
    person, asset = upload(client)
    profile = link_material(client, person, asset)
    with SessionLocal() as db:
        db.add(
            Transcript(
                tenant_id=get_settings().default_tenant_id, source_asset_id=UUID(asset["id"])
            )
        )
        db.commit()
    assert client.delete(f"/v1/evidence/assets/{asset['id']}").status_code == 409
    assert client.get("/v1/life-profiles/" + profile["id"]).json() == profile
    with SessionLocal() as db:
        assert db.get(SourceAsset, UUID(asset["id"])) is not None


def test_delete_failure_rolls_back_profile_and_asset_together(client, monkeypatch):
    from lifereel_api.modules.evidence.service import delete_asset
    from lifereel_api.modules.interview import profile_service

    person, asset = upload(client)
    profile = link_material(client, person, asset)
    apply = profile_service.patch

    def fail_after_patch(*args, **kwargs):
        apply(*args, **kwargs)
        raise RuntimeError("synthetic deletion failure")

    monkeypatch.setattr(profile_service, "patch", fail_after_patch)
    with SessionLocal() as db:
        with pytest.raises(RuntimeError, match="synthetic deletion failure"):
            delete_asset(db, get_settings().default_tenant_id, UUID(asset["id"]))
        db.rollback()
    assert client.get("/v1/life-profiles/" + profile["id"]).json() == profile
    with SessionLocal() as db:
        assert db.get(SourceAsset, UUID(asset["id"])) is not None


def test_completed_upload_permit_does_not_block_deletion(client):
    from lifereel_api.modules.evidence.models import EvidenceUpload

    from lifereel_api.core.models import utcnow

    person, asset = upload(client)
    with SessionLocal() as db:
        permit = EvidenceUpload(
            tenant_id=get_settings().default_tenant_id,
            subject_id=UUID(person["id"]),
            original_filename="memoir.txt",
            mime_type="text/plain",
            kind="document",
            byte_size=32,
            consent_scope="private",
            storage_key="synthetic-delete-permit",
            expires_at=utcnow(),
            asset_id=UUID(asset["id"]),
        )
        db.add(permit)
        db.commit()
        permit_id = permit.id
    assert client.delete(f"/v1/evidence/assets/{asset['id']}").status_code == 204
    with SessionLocal() as db:
        assert db.get(EvidenceUpload, permit_id).asset_id is None


def test_job_reference_blocks_deletion(client):
    from lifereel_api.modules.jobs.models import Job

    _, asset = upload(client)
    with SessionLocal() as db:
        db.add(
            Job(
                tenant_id=get_settings().default_tenant_id,
                kind="synthetic",
                status="succeeded",
                payload={"nested": [{"asset_id": asset["id"]}]},
            )
        )
        db.commit()
    response = client.delete(f"/v1/evidence/assets/{asset['id']}")
    assert response.status_code == 409, response.text


def test_viewer_cannot_delete_asset(client):
    from lifereel_api.modules.auth.dependencies import AuthContext, auth_context

    from lifereel_api.main import app

    _, asset = upload(client)
    app.dependency_overrides[auth_context] = lambda: AuthContext(
        None,
        get_settings().default_tenant_id,
        "viewer",
    )
    try:
        assert client.delete(f"/v1/evidence/assets/{asset['id']}").status_code == 403
    finally:
        app.dependency_overrides.pop(auth_context)
    assert client.get(f"/v1/evidence/assets/{asset['id']}/content").status_code == 200

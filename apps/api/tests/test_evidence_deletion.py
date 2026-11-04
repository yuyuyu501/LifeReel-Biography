from io import BytesIO
from uuid import UUID, uuid4

import pytest
from lifereel_api.modules.evidence.models import SourceAsset, Transcript
from lifereel_api.modules.interview.profile_models import LifeProfile, LifeProfileEntry
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


@pytest.mark.parametrize("reference", ["profile", "transcript"])
def test_referenced_asset_is_preserved(client, reference):
    person, asset = upload(client)
    with SessionLocal() as db:
        tenant = get_settings().default_tenant_id
        if reference == "transcript":
            db.add(Transcript(tenant_id=tenant, source_asset_id=UUID(asset["id"])))
        else:
            profile = db.scalar(
                select(LifeProfile).where(LifeProfile.subject_id == UUID(person["id"]))
            )
            if profile is None:
                profile = LifeProfile(
                    tenant_id=tenant, subject_id=UUID(person["id"]), template_version="test"
                )
                db.add(profile)
                db.flush()
            db.add(
                LifeProfileEntry(
                    tenant_id=tenant,
                    profile_id=profile.id,
                    field_key="materials.assets[]",
                    record_key="test",
                    value={"asset_id": asset["id"]},
                )
            )
        db.commit()
    url = f"/v1/evidence/assets/{asset['id']}"
    response = client.delete(url)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "EVIDENCE_ASSET_IN_USE"
    assert client.get(url + "/content").status_code == 200
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

import base64
import hashlib
import json
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.models import utcnow
from lifereel_api.modules.evidence import direct_uploads
from lifereel_api.modules.evidence.models import EvidenceUpload, SourceAsset
from lifereel_api.modules.identity.models import Tenant


@pytest.fixture
def oss(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "oss_direct_upload_enabled", True)
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_endpoint_url", "https://oss-cn-shenzhen.aliyuncs.com")
    monkeypatch.setattr(settings, "s3_bucket", "test-bucket")
    monkeypatch.setattr(settings, "s3_access_key", "test-id")
    monkeypatch.setattr(settings, "s3_secret_key", "test-secret")
    remote = Mock()
    storage = SimpleNamespace(client=remote, bucket="test-bucket")
    monkeypatch.setattr(direct_uploads, "S3PrivateStorage", lambda: storage)
    return remote


def permit(client, **changes):
    person = client.post("/v1/persons", json={"display_name": "OSS Test"}).json()
    payload = dict(
        subject_id=person["id"],
        kind="document",
        original_filename="memory.txt",
        mime_type="text/plain",
        byte_size=6,
    )
    payload.update(changes)
    response = client.post("/v1/evidence/assets/direct-upload", json=payload)
    return response, payload


def remote_file(oss, data=b"memory", mime="text/plain"):
    oss.head_object.return_value = {
        "ContentLength": len(data),
        "ContentType": mime,
        "ETag": '"etag"',
    }
    oss.get_object.side_effect = lambda **kwargs: {
        "Body": StreamingBody(BytesIO(data), len(data)),
    }


def finish(client, permit):
    return client.post(
        "/v1/evidence/assets/complete-direct-upload", json={"upload_id": permit["upload_id"]}
    )


def test_policy_is_scoped_and_pending_is_not_visible(client, oss):
    response, payload = permit(client)
    assert response.status_code == 200
    result = response.json()
    policy = json.loads(base64.b64decode(result["fields"]["policy"]))
    assert result["url"] == "https://test-bucket.oss-cn-shenzhen.aliyuncs.com"
    assert {"key": result["fields"]["key"]} in policy["conditions"]
    assert payload["subject_id"] in result["fields"]["key"]
    assert {"x-oss-forbid-overwrite": "true"} in policy["conditions"]
    assert ["content-length-range", 6, 6] in policy["conditions"]
    assert "test-secret" not in response.text
    assert client.get("/v1/evidence/assets").json() == []


@pytest.mark.parametrize(
    "kind,mime,data",
    [
        ("document", "text/plain", b"memory"),
        ("photo", "image/png", b"\x89PNG\r\n\x1a\nimage"),
        ("audio", "audio/wav", b"RIFF1234WAVEaudio"),
        ("video", "video/mp4", b"0000ftypisomvideo"),
    ],
)
def test_four_kinds_complete_with_verified_hash_and_idempotency(client, oss, kind, mime, data):
    response, payload = permit(client, kind=kind, mime_type=mime, byte_size=len(data))
    remote_file(oss, data, mime)
    first = finish(client, response.json())
    assert first.status_code == 201
    asset = first.json()
    assert asset["sha256"] == hashlib.sha256(data).hexdigest()
    assert asset["subject_id"] == payload["subject_id"]
    second = finish(client, response.json())
    assert second.json()["id"] == asset["id"]
    assert oss.get_object.call_count == 1
    assert oss.copy_object.call_count == 1
    assert not oss.copy_object.call_args.kwargs["Key"].startswith(direct_uploads.STAGING_PREFIX)
    assert oss.copy_object.call_args.kwargs["CopySourceIfMatch"] == '"etag"'
    assert len(client.get("/v1/evidence/assets").json()) == 1
    oss.delete_object.assert_called_once()


def test_same_subject_dedup_and_different_subject_isolation(client, oss):
    response, payload = permit(client)
    remote_file(oss)
    first = finish(client, response.json()).json()
    duplicate = client.post("/v1/evidence/assets/direct-upload", json=payload).json()
    assert finish(client, duplicate).json()["id"] == first["id"]
    another, _ = permit(client)
    assert finish(client, another.json()).json()["id"] != first["id"]


def test_fake_image_is_rejected_without_copy_or_asset(client, oss):
    response, _ = permit(client, kind="photo", mime_type="image/png")
    remote_file(oss, b"memory", "image/png")
    result = finish(client, response.json())
    assert result.status_code == 415
    oss.copy_object.assert_not_called()
    assert client.get("/v1/evidence/assets").json() == []


def test_metadata_mismatch_and_missing_object(client, oss):
    response, _ = permit(client)
    remote_file(oss, b"bad size")
    assert finish(client, response.json()).status_code == 400
    oss.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")
    assert finish(client, response.json()).status_code == 400
    oss.get_object.assert_not_called()


def test_expired_or_unknown_permit_is_rejected(client, oss):
    response, _ = permit(client)
    with SessionLocal() as db:
        upload = db.get(EvidenceUpload, UUID(response.json()["upload_id"]))
        upload.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert finish(client, response.json()).status_code == 410
    assert finish(client, {"upload_id": str(uuid4())}).status_code == 404
    oss.head_object.assert_not_called()


@pytest.mark.parametrize(
    "kind,mime,limit",
    [
        ("photo", "image/png", 20 * 1024 * 1024),
        ("document", "text/plain", 50 * 1024 * 1024),
        ("audio", "audio/wav", 500 * 1024 * 1024),
        ("video", "video/mp4", 2 * 1024 * 1024 * 1024),
    ],
)
def test_size_limits_before_issuing_permit(client, oss, kind, mime, limit):
    response, _ = permit(client, kind=kind, mime_type=mime, byte_size=limit + 1)
    assert response.status_code == 413


def test_tenant_and_session_scope_before_permit_and_finalize(client, oss):
    response, payload = permit(client)
    other_tenant = uuid4()
    with SessionLocal() as db:
        db.add(Tenant(id=other_tenant, name="Other", slug=str(other_tenant)))
        db.commit()
    headers = {"X-Tenant-ID": str(other_tenant)}
    assert (
        client.post("/v1/evidence/assets/direct-upload", json=payload, headers=headers).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/evidence/assets/complete-direct-upload",
            json={"upload_id": response.json()["upload_id"]},
            headers=headers,
        ).status_code
        == 404
    )
    payload["interview_session_id"] = str(uuid4())
    assert client.post("/v1/evidence/assets/direct-upload", json=payload).status_code == 404
    oss.head_object.assert_not_called()


def test_permit_limit_and_disabled_config(client, oss, monkeypatch):
    response, payload = permit(client)
    for _ in range(9):
        assert client.post("/v1/evidence/assets/direct-upload", json=payload).status_code == 200
    assert client.post("/v1/evidence/assets/direct-upload", json=payload).status_code == 429
    monkeypatch.setattr(get_settings(), "oss_direct_upload_enabled", False)
    assert client.get("/v1/evidence/upload-settings").json() == {"direct_upload": False}
    assert client.post("/v1/evidence/assets/direct-upload", json=payload).status_code == 503


def test_cleanup_failure_does_not_undo_success(client, oss):
    response, _ = permit(client)
    remote_file(oss)
    oss.delete_object.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "Delete")
    assert finish(client, response.json()).status_code == 201
    with SessionLocal() as db:
        assert db.scalar(select(SourceAsset)) is not None

from uuid import uuid4

from lifereel_api.core.config import get_settings
from lifereel_api.modules.evidence.storage import S3PrivateStorage


def test_evidence_redirect_is_tenant_scoped_and_does_not_stream(client, monkeypatch):
    person = client.post("/v1/persons", json={"display_name": "直读测试"}).json()
    asset = client.post(
        "/v1/evidence/assets",
        data={"subject_id": person["id"], "kind": "audio"},
        files={"file": ("test.ogg", b"OggSsynthetic-audio", "audio/ogg")},
    ).json()
    monkeypatch.setattr(get_settings(), "storage_backend", "s3")
    signed = []

    def sign(self, key, **kwargs):
        signed.append((key, kwargs))
        return "https://bucket.example/test?signature=temporary"

    monkeypatch.setattr(S3PrivateStorage, "signed_url", sign)
    response = client.get(f"/v1/evidence/assets/{asset['id']}/content", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["cache-control"] == "private, no-store"
    assert signed[0][1] == {"expires_in": 900}
    response = client.get(
        f"/v1/evidence/assets/{asset['id']}/content",
        headers={"X-Tenant-ID": str(uuid4())},
        follow_redirects=False,
    )
    assert response.status_code == 404
    assert len(signed) == 1


def test_storage_signs_short_expiry_without_unsupported_oss_overrides():
    calls = []

    class Client:
        def generate_presigned_url(self, operation, **kwargs):
            calls.append((operation, kwargs))
            return "https://example/signed"

    storage = object.__new__(S3PrivateStorage)
    storage.client = Client()
    storage.bucket = "private"
    storage.signed_url("LifeReel-Biography/test.mp4", expires_in=900)
    assert calls[0][1]["ExpiresIn"] == 900
    assert calls[0][1]["Params"] == {"Bucket": "private", "Key": "LifeReel-Biography/test.mp4"}


def test_documents_keep_inline_site_preview(client, monkeypatch):
    from lifereel_api.modules.evidence.storage import media_redirect
    monkeypatch.setattr(get_settings(), "storage_backend", "s3")
    assert media_redirect("test.pdf", "application/pdf") is None
    assert media_redirect("test.txt", "text/plain") is None


def test_new_s3_videos_store_correct_content_type():
    from io import BytesIO
    from types import SimpleNamespace

    from botocore.exceptions import ClientError
    calls = []
    class Client:
        exceptions = SimpleNamespace(ClientError=ClientError)
        def head_object(self, **kwargs):
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        def upload_fileobj(self, *args, **kwargs):
            calls.append(kwargs)
    storage = object.__new__(S3PrivateStorage)
    storage.client, storage.bucket = Client(), "private"
    storage.put_file("LifeReel-Biography/generated/test.mp4", BytesIO(b"test"))
    assert calls[0]["ExtraArgs"]["ContentType"] == "video/mp4"


def test_streaming_private_file_does_not_read_whole_object(monkeypatch):
    from lifereel_api.modules.evidence import storage

    class StreamingStorage:
        def iter_range(self, key, start, end):
            assert (key, start, end) == ("test", 0, 5)
            yield b"abc"
            yield b"def"

    monkeypatch.setattr(storage, "private_storage", StreamingStorage)
    with storage.private_file("test", 6, ".mp4") as path:
        assert path.read_bytes() == b"abcdef"
    assert not path.exists()


def test_final_and_segment_video_redirects_are_private(client, monkeypatch):
    from test_production_chapters import make_script

    from lifereel_api.core.database import SessionLocal
    from lifereel_api.modules.production.models import GeneratedAsset, ProductionRun

    project, _ = make_script(client)
    tenant = get_settings().default_tenant_id
    with SessionLocal() as db:
        run = ProductionRun(tenant_id=tenant, project_id=project.id, status="completed")
        db.add(run)
        db.flush()
        key = f"LifeReel-Biography/generated/{tenant}/{run.id}/segment-0.mp4"
        run.output_manifest = {"segments": [{"status": "completed", "storage_key": key}]}
        asset = GeneratedAsset(
            tenant_id=tenant,
            production_run_id=run.id,
            kind="final_video",
            provider="test",
            mime_type="video/mp4",
            storage_key=key,
            sha256="0" * 64,
        )
        db.add(asset)
        db.commit()
        asset_id, run_id = asset.id, run.id
    monkeypatch.setattr(get_settings(), "storage_backend", "s3")
    monkeypatch.setattr(S3PrivateStorage, "signed_url", lambda *args, **kw: "https://example/video")
    for url in (
        f"/v1/production/assets/{asset_id}/content",
        f"/v1/production/runs/{run_id}/segments/0/content",
    ):
        assert client.get(url, follow_redirects=False).status_code == 307
        assert (
            client.get(
                url, headers={"X-Tenant-ID": str(uuid4())}, follow_redirects=False
            ).status_code
            == 404
        )

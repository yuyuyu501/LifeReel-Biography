"""Opt-in live OSS check. Run inside the API container; uses no AI."""

from __future__ import annotations

import argparse
import hashlib
from uuid import UUID, uuid4
from xml.etree import ElementTree

import httpx
from sqlalchemy import delete, select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.main import app as application  # noqa: F401
from lifereel_api.modules.evidence.models import EvidenceUpload, SourceAsset
from lifereel_api.modules.evidence.storage import S3PrivateStorage
from lifereel_api.modules.identity.models import Person


def cleanup(person_id: UUID):
    storage = S3PrivateStorage()
    with SessionLocal() as db:
        person = db.get(Person, person_id)
        if not person or not person.display_name.startswith("OSS smoke "):
            raise RuntimeError("NOT_A_SMOKE_TEST_PERSON")
        keys = list(
            db.scalars(
                select(SourceAsset.storage_key).where(
                    SourceAsset.subject_id == person_id,
                )
            )
        )
        keys += list(
            db.scalars(
                select(EvidenceUpload.storage_key).where(
                    EvidenceUpload.subject_id == person_id,
                )
            )
        )
        for key in keys:
            storage.client.delete_object(Bucket=storage.bucket, Key=key)
        db.execute(delete(EvidenceUpload).where(EvidenceUpload.subject_id == person_id))
        db.execute(delete(SourceAsset).where(SourceAsset.subject_id == person_id))
        db.execute(delete(Person).where(Person.id == person_id))
        db.commit()
    print("Only this run's synthetic objects and person removed", flush=True)


def main():
    settings = get_settings()
    person_id = None
    with (
        httpx.Client(
            base_url="http://127.0.0.1:8000",
            timeout=120,
            headers={
                "X-API-Key": settings.api_access_key,
                "X-Tenant-ID": str(settings.default_tenant_id),
            },
        ) as app,
        httpx.Client(timeout=120) as cloud,
    ):
        try:
            response = app.post("/v1/persons", json={"display_name": f"OSS smoke {uuid4()}"})
            assert response.status_code == 201, response.status_code
            person_id = UUID(response.json()["id"])
            for kind, mime, filename, content in [
                ("document", "text/plain", "memory.txt", b"OSS synthetic document"),
                ("photo", "image/png", "photo.png", b"\x89PNG\r\n\x1a\nsynthetic image"),
                ("audio", "audio/wav", "voice.wav", b"RIFF1234WAVEsynthetic audio"),
                ("video", "video/mp4", "video.mp4", b"0000ftypisomsynthetic video"),
            ]:
                response = app.post(
                    "/v1/evidence/assets/direct-upload",
                    json={
                        "subject_id": str(person_id),
                        "kind": kind,
                        "mime_type": mime,
                        "original_filename": filename,
                        "byte_size": len(content),
                    },
                )
                assert response.status_code == 200, response.text
                permit = response.json()
                origin = {"Origin": "http://127.0.0.1:5173"}
                result = cloud.post(
                    permit["url"],
                    data=permit["fields"],
                    files={"file": (filename, content, mime)},
                    headers=origin,
                )
                if result.status_code != 204:
                    code = ElementTree.fromstring(result.content).findtext("Code")
                    raise RuntimeError(f"OSS_POST_FAILED:{result.status_code}:{code}")
                assert result.headers.get("access-control-allow-origin") in {
                    "*",
                    "http://127.0.0.1:5173",
                }
                replay = cloud.post(
                    permit["url"],
                    data=permit["fields"],
                    files={"file": (filename, content, mime)},
                    headers=origin,
                )
                assert replay.status_code == 409, f"OVERWRITE_ALLOWED:{replay.status_code}"
                assert cloud.get(f"{permit['url']}/{permit['fields']['key']}").status_code == 403
                response = app.post(
                    "/v1/evidence/assets/complete-direct-upload",
                    json={"upload_id": permit["upload_id"]},
                )
                assert response.status_code == 201, response.text
                asset = response.json()
                assert asset["sha256"] == hashlib.sha256(content).hexdigest()
                assert app.get(f"/v1/evidence/assets/{asset['id']}/content").content == content
                assert (
                    app.get(
                        f"/v1/evidence/assets/{asset['id']}/content", headers={"Range": "bytes=0-3"}
                    ).content
                    == content[:4]
                )
                repeat = app.post(
                    "/v1/evidence/assets/complete-direct-upload",
                    json={"upload_id": permit["upload_id"]},
                )
                assert repeat.json()["id"] == asset["id"]
                print(f"{kind}: post/cors/private/overwrite/hash/range/idempotency OK", flush=True)
            response = app.post(
                "/v1/evidence/assets/direct-upload",
                json={
                    "subject_id": str(person_id),
                    "kind": "document",
                    "mime_type": "text/plain",
                    "original_filename": "invalid.txt",
                    "byte_size": 5,
                },
            )
            permit = response.json()
            result = cloud.post(
                permit["url"],
                data=permit["fields"],
                files={"file": ("invalid.txt", b"too many bytes", "text/plain")},
            )
            assert result.status_code == 400, f"SIZE_NOT_ENFORCED:{result.status_code}"
            print("oversize POST rejected OK", flush=True)
        finally:
            if person_id:
                cleanup(person_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup-person", type=UUID)
    args = parser.parse_args()
    if args.cleanup_person:
        cleanup(args.cleanup_person)
    else:
        main()

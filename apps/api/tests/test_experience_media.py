import copy
import hashlib
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_segmented_production import setup_pipeline

from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError
from lifereel_api.modules.billing.models import Charge
from lifereel_api.modules.evidence.storage import private_storage
from lifereel_api.modules.production import quality, regeneration, retention, segmented
from lifereel_api.modules.production.models import ProductionRun
from lifereel_api.modules.production.providers import ProviderOutput


def completed_run(client, monkeypatch):
    payload = setup_pipeline(client, monkeypatch)
    calls = []

    class Provider:
        def __init__(self, options):
            self.client = self

        def close(self):
            pass

        def submit_segment(self, prompt, duration, frame, **kwargs):
            calls.append(prompt)
            return f"task-{len(calls)}"

        def fetch_segment(self, task_id, duration):
            return ProviderOutput(task_id.encode(), "video/mp4", "mp4", {})

    monkeypatch.setattr(segmented, "VolcengineSeedanceProvider", Provider)
    monkeypatch.setattr(quality, "collect_review_frames", lambda *args: [])
    response = client.post("/v1/production/runs", json=payload)
    assert response.status_code == 201, response.text
    run = response.json()
    for _ in range(3):
        response = client.post(f"/v1/production/runs/{run['id']}/execute")
        assert response.status_code == 200, response.text
        run = response.json()
    assert run["status"] == "completed"
    return run, calls


def test_local_regeneration_reuses_media_charges_once_and_preserves_original(client, monkeypatch):
    source, calls = completed_run(client, monkeypatch)
    base = f"/v1/production/runs/{source['id']}/segments/0"
    quote = client.get(base + "/quote")
    assert quote.status_code == 200, quote.text
    price = quote.json()
    assert price["target_seconds"] == 15
    assert price["amount_cents"] == 300
    payload = {
        "request_id": str(uuid4()),
        "expected_script_version": price["script_version"],
        "quoted_amount_cents": price["amount_cents"],
    }
    response = client.post(base + "/regenerate", json=payload)
    assert response.status_code == 200, response.text
    new = response.json()
    assert new["id"] != source["id"]
    assert client.post(base + "/regenerate", json=payload).json()["id"] == new["id"]
    assert (
        client.post(base + "/regenerate", json={**payload, "quoted_amount_cents": 1}).status_code
        == 409
    )
    for _ in range(3):
        new = client.post(f"/v1/production/runs/{new['id']}/execute").json()
    assert new["status"] == "completed", new
    assert len(calls) == 3
    segments = new["output_manifest"]["segments"]
    assert segments[1]["reused"] is True
    assert segments[1]["sha256"] == source["output_manifest"]["segments"][1]["sha256"]
    assert new["output_manifest"]["completed_segments"] == 2
    assert client.get(f"/v1/production/runs/{new['id']}/segments/1/content").content == b"task-2"
    with SessionLocal() as db:
        row = db.get(ProductionRun, UUID(source["id"]))
        retention.cleanup_project(db, row.tenant_id, row.project_id)
        db.refresh(row)
        assert not row.output_manifest.get("media_retention")
        charge = db.scalar(select(Charge).where(Charge.business_key == "video:" + new["id"]))
        assert charge.amount_cents == 300
        assert charge.status == "settled"
    assert (
        client.get(f"/v1/production/assets/{source['assets'][0]['id']}/content").status_code == 200
    )
    assert client.post(base + "/regenerate", json=payload).json()["id"] == new["id"]


def test_regeneration_checks_owner_version_quote_and_source_hash(client, monkeypatch):
    source, calls = completed_run(client, monkeypatch)
    base = f"/v1/production/runs/{source['id']}/segments/0"
    price = client.get(base + "/quote").json()
    payload = {
        "request_id": str(uuid4()),
        "expected_script_version": price["script_version"],
        "quoted_amount_cents": price["amount_cents"],
    }
    assert (
        client.post(base + "/regenerate", json={**payload, "quoted_amount_cents": 0}).status_code
        == 409
    )
    assert (
        client.post(
            base + "/regenerate", json={**payload, "expected_script_version": 999}
        ).status_code
        == 409
    )
    with SessionLocal() as db:
        with pytest.raises(ApiError) as error:
            regeneration.quote(db, uuid4(), UUID(source["id"]), 0)
        assert error.value.status_code == 404
    new = client.post(base + "/regenerate", json=payload).json()
    key = source["output_manifest"]["segments"][1]["storage_key"]
    private_storage().delete(key)
    private_storage().put(key, b"corrupted")
    new = client.post(f"/v1/production/runs/{new['id']}/execute").json()
    assert new["status"] == "failed"
    assert len(calls) == 2
    with SessionLocal() as db:
        charge = db.scalar(select(Charge).where(Charge.business_key == "video:" + new["id"]))
        assert charge.status == "released"


def test_identity_keeps_first_reference_on_later_shots_and_uses_only_official_tail(monkeypatch):
    monkeypatch.setattr(
        quality.appearance, "inputs", lambda *args: {"reference_images": ["portrait", "place"]}
    )
    monkeypatch.setattr(
        quality, "prepare_original", lambda *args: (b"tail", {"reference_mime": "image/png"}, {})
    )
    manifest = {"segments": [{"official_tail": {"sha256": "original"}}, {}]}
    result = quality.identity_inputs(None, None, manifest, None, None, 1)
    assert result["reference_images"][:2] == ["portrait", "place"]
    assert result["reference_images"][2].startswith("data:image/png;base64,")
    assert "reference_video_url" not in result
    monkeypatch.setattr(
        quality.appearance, "inputs", lambda *args: {"reference_images": list(range(9))}
    )
    assert quality.identity_inputs(None, None, manifest, None, None, 1)["reference_images"] == list(
        range(9)
    )


def test_review_frames_authorized_and_retained_with_run(client, monkeypatch):
    source, _ = completed_run(client, monkeypatch)
    with SessionLocal() as db:
        run = db.get(ProductionRun, UUID(source["id"]))
        manifest = copy.deepcopy(run.output_manifest)
        key = f"LifeReel-Biography/generated/{run.tenant_id}/{run.id}/review/0-0.jpg"
        image = b"\xff\xd8synthetic-jpeg"
        private_storage().put(key, image)
        manifest["segments"][0]["review_frames"] = [
            {
                "position": 0,
                "at_seconds": 2,
                "storage_key": key,
                "sha256": hashlib.sha256(image).hexdigest(),
            }
        ]
        run.output_manifest = manifest
        db.commit()
    url = f"/v1/production/runs/{source['id']}/segments/0/review/0"
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.content == image
    assert client.get(url[:-1] + "99").status_code == 404
    with SessionLocal() as db:
        run = db.get(ProductionRun, UUID(source["id"]))
        run.output_manifest = {**run.output_manifest, "media_retention": {"status": "deleted"}}
        db.commit()
    assert client.get(url).status_code == 404


def test_progress_does_not_invent_estimate(client, monkeypatch):
    source, _ = completed_run(client, monkeypatch)
    response = client.get(f"/v1/production/runs/{source['id']}/progress")
    assert response.status_code == 200
    assert response.json()["estimated_seconds"] is None
    assert response.json()["sample_count"] == 1

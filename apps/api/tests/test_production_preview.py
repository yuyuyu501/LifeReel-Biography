from uuid import UUID

import pytest
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.production import planning
from lifereel_api.modules.production.models import ProductionRun
from lifereel_api.modules.script.models import ScriptShot
from test_segmented_production import setup_pipeline

from lifereel_api.core.database import SessionLocal


def _counts():
    with SessionLocal() as db:
        return (
            len(list(db.query(ProductionRun).all())),
            len(list(db.query(Job).all())),
        )


def test_preview_is_read_only_and_start_requires_its_confirmation(raw_client, monkeypatch):
    payload = setup_pipeline(raw_client, monkeypatch)
    monkeypatch.setattr(
        planning,
        "OpenAICompatibleClient",
        lambda *_: pytest.fail("preview must not call a planning model"),
    )

    preview = raw_client.post("/v1/production/preview", json=payload)
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert len(result["segments"]) == 2
    assert result["segments"][0]["duration_seconds"] == 15
    assert result["segments"][0]["shot_id"]
    assert result["segments"][0]["source_claim_ids"] == []
    assert result["segments"][0]["provider_prompt"].startswith("连续纪实镜头")
    assert result["generation_config"]["model"].startswith("doubao-seedance-2-")
    assert result["billing_quote"]["amount_cents"] == 600
    assert _counts() == (0, 0)

    missing_confirmation = raw_client.post("/v1/production/runs", json=payload)
    assert missing_confirmation.status_code == 422
    assert _counts() == (0, 0)


def test_stale_preview_cannot_create_a_job_or_reserve_cost(raw_client, monkeypatch):
    payload = setup_pipeline(raw_client, monkeypatch)
    preview = raw_client.post("/v1/production/preview", json=payload).json()
    with SessionLocal() as db:
        shot = db.query(ScriptShot).filter_by(scene_id=UUID(payload["scene_id"])).first()
        shot.visual_prompt = "修改后的镜头画面"
        db.commit()

    response = raw_client.post(
        "/v1/production/runs",
        json={
            **payload,
            "quoted_amount_cents": preview["billing_quote"]["amount_cents"],
            "preview_fingerprint": preview["fingerprint"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PRODUCTION_PREVIEW_STALE"
    assert _counts() == (0, 0)


def test_confirmed_preview_freezes_the_exact_plan_into_the_run(raw_client, monkeypatch):
    payload = setup_pipeline(raw_client, monkeypatch)
    preview = raw_client.post("/v1/production/preview", json=payload).json()

    response = raw_client.post(
        "/v1/production/runs",
        json={
            **payload,
            "quoted_amount_cents": preview["billing_quote"]["amount_cents"],
            "preview_fingerprint": preview["fingerprint"],
        },
    )
    assert response.status_code == 201, response.text
    manifest = response.json()["output_manifest"]
    assert manifest["preview_fingerprint"] == preview["fingerprint"]
    assert manifest["plan"]["continuity"] == preview["plan"]["continuity"]
    assert [
        segment["provider_prompt"] for segment in manifest["segments"]
    ] == [segment["provider_prompt"] for segment in preview["segments"]]
    assert all(segment["status"] == "pending" for segment in manifest["segments"])

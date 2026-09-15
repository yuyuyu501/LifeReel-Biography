from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_script_editing import setup_script

from lifereel_api.core.database import SessionLocal
from lifereel_api.core.models import utcnow
from lifereel_api.modules.evidence.storage import LocalPrivateStorage
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.production import retention
from lifereel_api.modules.production.models import GeneratedAsset, ProductionRun
from lifereel_api.modules.publication.models import Publication


def add_run(db, project, days=0, status="completed", chapter=None):
    run = ProductionRun(tenant_id=project.tenant_id, project_id=project.project_id,
                        status=status, provider="mock", created_at=utcnow() + timedelta(days=days),
                        output_manifest={"script_snapshot": [{"chapter_id": chapter or "first"}],
                                         "billing": {"status": "settled", "charged_cents": 42}})
    db.add(run)
    db.flush()
    prefix = f"LifeReel-Biography/generated/{run.tenant_id}/{run.id}/"
    key = prefix + "final.mp4"
    asset = GeneratedAsset(tenant_id=run.tenant_id, production_run_id=run.id, kind="final_video",
                           mime_type="video/mp4", storage_key=key, sha256="test", provider="mock")
    db.add(asset)
    segment = prefix + "segment-0.mp4"
    tail = prefix + "originals/tail"
    run.output_manifest = {**run.output_manifest, "segments": [
        {"storage_key": segment, "official_tail": {"storage_key": tail}, "status": "completed"},
    ]}
    storage = LocalPrivateStorage()
    for name in [key, segment, tail]:
        storage.put(name, b"synthetic test data")
    db.commit()
    return run, [key, segment, tail]


def fixture_project(client):
    _, _, _, script = setup_script(client)
    from types import SimpleNamespace

    from lifereel_api.core.config import get_settings
    return SimpleNamespace(
        tenant_id=get_settings().default_tenant_id, project_id=UUID(script["id"]),
    )


def test_success_retires_only_older_same_chapter_media_preserving_billing(client):
    project = fixture_project(client)
    wallet_before = client.get("/v1/wallet").json()
    with SessionLocal() as db:
        old, old_keys = add_run(db, project, -2)
        other, other_keys = add_run(db, project, -1, chapter="second")
        new, new_keys = add_run(db, project)
        newer_failed, failed_keys = add_run(db, project, 1, status="failed")
        pub = Publication(tenant_id=project.tenant_id, production_run_id=old.id,
                          subject_id=UUID(client.get("/v1/persons").json()[0]["id"]),
                          audience="family", access_token=str(uuid4()), published_at=utcnow())
        db.add(pub)
        db.commit()
        retention.cleanup_project(db, project.tenant_id, project.project_id)
        assert old.output_manifest["media_retention"]["status"] == "deleted"
        assert old.output_manifest["billing"]["charged_cents"] == 42
        assert old.status == "completed"
        assert pub.status == "withdrawn"
        assert not retention.is_retired(other)
        assert not retention.is_retired(newer_failed)
        for key in old_keys:
            with pytest.raises(FileNotFoundError):
                LocalPrivateStorage().get(key)
        for key in [*other_keys, *new_keys, *failed_keys]:
            assert LocalPrivateStorage().get(key)
        assert not db.scalar(select(GeneratedAsset).where(
            GeneratedAsset.production_run_id == old.id,
        ))
        retention.cleanup_project(db, project.tenant_id, project.project_id)
    assert client.get("/v1/wallet").json() == wallet_before


def test_no_success_keeps_previous_video_and_failure_cleanup_is_retried(client, monkeypatch):
    project = fixture_project(client)
    with SessionLocal() as db:
        old, keys = add_run(db, project, -2)
        new, _ = add_run(db, project, status="running")
        retention.cleanup_project(db, project.tenant_id, project.project_id)
        assert not retention.is_retired(old)
        new.status = "completed"
        job = retention.schedule(db, new)
        db.commit()
        original = LocalPrivateStorage.delete
        monkeypatch.setattr(LocalPrivateStorage, "delete", lambda *args: (_ for _ in ()).throw(
            RuntimeError("temporary storage outage")))
        retention.execute_cleanup(db, job)
        assert job.status == "queued"
        assert old.output_manifest["media_retention"]["status"] == "pending"
        assert LocalPrivateStorage().get(keys[0])
        assert client.get(f"/v1/production/runs/{old.id}/segments/0/content").status_code == 404
        monkeypatch.setattr(LocalPrivateStorage, "delete", original)
        retention.execute_cleanup(db, job)
        assert job.status == "completed"
        assert old.output_manifest["media_retention"]["status"] == "deleted"


def test_never_deletes_uploads_or_other_run_keys(client):
    project = fixture_project(client)
    with SessionLocal() as db:
        old, _ = add_run(db, project, -2)
        new, _ = add_run(db, project)
        foreign_key = f"LifeReel-Biography/evidence/{project.tenant_id}/photo.jpg"
        LocalPrivateStorage().put(foreign_key, b"original")
        old.output_manifest = {**old.output_manifest, "segments": [{"storage_key": foreign_key}]}
        db.commit()
        with pytest.raises(ValueError, match="MEDIA_RETENTION_KEY_INVALID"):
            retention.cleanup_project(db, project.tenant_id, project.project_id)
        assert LocalPrivateStorage().get(foreign_key) == b"original"
        assert not retention.is_retired(old)
        assert not retention.is_retired(new)


def test_completed_render_schedules_durable_cleanup(client):
    _, _, _, script = setup_script(client)
    run = client.post("/v1/production/runs", json={"project_id": script["id"],
                     "scene_id": script["scenes"][0]["id"], "provider": "mock"}).json()
    assert run["status"] == "completed"
    with SessionLocal() as db:
        assert db.scalar(select(Job).where(Job.idempotency_key == f"media-retention:{run['id']}"))


def test_cleanup_runs_in_video_lane_and_backoff_does_not_block_rendering(client, monkeypatch):
    from lifereel_api.core.config import get_settings
    from lifereel_api.modules.jobs.dispatch import claim_job, execute_claim

    monkeypatch.setattr(get_settings(), "job_queue_backend", "database")
    project = fixture_project(client)
    with SessionLocal() as db:
        old, _ = add_run(db, project, -2)
        new, _ = add_run(db, project)
        job = retention.schedule(db, new)
        db.commit()
        claim = claim_job(db, "video")
        assert claim["job_id"] == str(job.id)
        result = execute_claim(db, job.id, UUID(claim["token"]))
        assert result["status"] == "completed"
        db.refresh(old)
        assert retention.is_retired(old)
        job.status = "queued"
        job.lease_token = None
        job.lease_expires_at = utcnow() + timedelta(hours=1)
        render = Job(tenant_id=project.tenant_id, kind="production.render", status="queued",
                     payload={}, idempotency_key="another-render")
        db.add(render)
        db.commit()
        assert claim_job(db, "video")["job_id"] == str(render.id)


def test_retired_failed_task_cannot_retry_or_publish(client):
    from lifereel_api.core.errors import ApiError
    from lifereel_api.modules.production.recovery import assert_retry_allowed

    project = fixture_project(client)
    with SessionLocal() as db:
        old, _ = add_run(db, project, -2, status="failed")
        add_run(db, project)
        retention.cleanup_project(db, project.tenant_id, project.project_id)
        with pytest.raises(ApiError):
            assert_retry_allowed(old)


def test_s3_deletion_targets_only_the_requested_key(monkeypatch):
    from types import SimpleNamespace

    from lifereel_api.modules.evidence.storage import S3PrivateStorage

    calls = []
    storage = S3PrivateStorage.__new__(S3PrivateStorage)
    storage.bucket = "synthetic"
    storage.client = SimpleNamespace(delete_object=lambda **kwargs: calls.append(kwargs))
    storage.delete("LifeReel-Biography/generated/tenant/run/final.mp4")
    assert calls == [{"Bucket": "synthetic",
                      "Key": "LifeReel-Biography/generated/tenant/run/final.mp4"}]

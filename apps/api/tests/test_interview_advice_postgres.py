"""Opt-in queue regression in a disposable PostgreSQL database and unique schema."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from lifereel_api.modules.identity.models import Tenant
from lifereel_api.modules.jobs import dispatch, service
from lifereel_api.modules.jobs.events import JobDelivery, OutboxEvent
from lifereel_api.modules.jobs.models import Job
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import Base
from lifereel_api.core.schema import SERVICE_SCHEMAS


def test_postgres_optional_jobs_filter_and_concurrent_admission(monkeypatch):
    url = os.environ.get("INTERVIEW_TEST_DATABASE_URL")
    if not url:
        pytest.skip("INTERVIEW_TEST_DATABASE_URL must name a disposable PostgreSQL database")
    parsed = make_url(url)
    assert parsed.database == "interview_hybrid_test" and parsed.host in {"localhost", "127.0.0.1"}
    engine = create_engine(url)
    schema = f"interview_advice_test_{uuid4().hex}"
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = engine.execution_options(
        schema_translate_map={None: schema, **dict.fromkeys(SERVICE_SCHEMAS, schema)}
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        Base.metadata.create_all(
            engine,
            tables=[
                Tenant.__table__,
                Job.__table__,
                JobDelivery.__table__,
                OutboxEvent.__table__,
            ],
        )
        monkeypatch.setattr(get_settings(), "job_queue_backend", "database")
        monkeypatch.setattr(get_settings(), "interview_concurrency", 3)
        tenant, session_id = uuid4(), str(uuid4())
        with factory() as db:
            db.add(Tenant(id=tenant, name="Disposable interview queue", slug=str(tenant)))
            db.commit()
            for i in range(4):
                service.create_job(
                    db, tenant, "interview.advice", {"session_id": session_id}, f"advice:{i}"
                )
            foreground, _ = service.create_job(db, tenant, "interview.turn.process", {}, "turn:1")
            db.commit()
            assert (
                db.scalar(select(Job).where(Job.payload["session_id"].as_string() == session_id))
                is not None
            )
            first = dispatch.claim_job(db, "interview")
            assert first["job_id"] == str(foreground.id)

        def claim(_):
            with factory() as db:
                return dispatch.claim_job(db, "interview")

        with ThreadPoolExecutor(max_workers=6) as pool:
            claims = [c for c in pool.map(claim, range(6)) if c]
        assert len(claims) == 1
        with factory() as db:
            assert db.get(Job, UUID(claims[0]["job_id"])).kind == "interview.advice"
            assert dispatch.claim_job(db, "interview") is None
            second, _ = service.create_job(db, tenant, "interview.turn.process", {}, "turn:2")
            db.commit()
            assert dispatch.claim_job(db, "interview")["job_id"] == str(second.id)
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()

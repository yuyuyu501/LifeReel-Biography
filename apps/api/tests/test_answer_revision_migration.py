from uuid import uuid4

from sqlalchemy import MetaData, Table, text
from sqlalchemy.orm import Session
from test_service_schemas import postgres  # noqa: F401

from alembic import command
from lifereel_api.core.models import utcnow
from lifereel_api.modules.identity.models import Person, Tenant
from lifereel_api.modules.interview.models import InterviewSession


def test_populated_revision_upgrade_defaults_and_rollback(postgres):  # noqa: F811
    engine, config = postgres
    command.upgrade(config, "20260929_0040")
    with Session(engine) as db:
        tenant = Tenant(name="Revision QA", slug=str(uuid4()))
        db.add(tenant)
        db.flush()
        person = Person(tenant_id=tenant.id, display_name="QA person")
        db.add(person)
        db.flush()
        interview = InterviewSession(tenant_id=tenant.id, subject_id=person.id)
        db.add(interview)
        db.flush()
        tenant_id, person_id, session_id = tenant.id, person.id, interview.id
        db.commit()
    answer, claim = uuid4(), uuid4()
    metadata = MetaData()
    rounds = Table("interview_rounds", metadata, schema="interview", autoload_with=engine)
    claims = Table("memory_claims", metadata, schema="memory", autoload_with=engine)
    with engine.begin() as db:
        db.execute(
            rounds.insert().values(
                id=answer,
                tenant_id=tenant_id,
                session_id=session_id,
                round_index=1,
                question_text="何时入学",
                question_intent="timeline",
                question_source="qa",
                answer_text="1998年入学",
                transcript_status="done",
                created_at=utcnow(),
            )
        )
        db.execute(
            claims.insert().values(
                id=claim,
                tenant_id=tenant_id,
                subject_id=person_id,
                source_round_id=answer,
                claim_text="1998年入学",
                source_quote="1998年入学",
                claim_type="recollection",
                confidence=1,
                review_status="unreviewed",
                extraction_provider="mock",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as db:
        result = db.execute(
            text(
                "SELECT answer_text,answer_version,answer_revisions "
                "FROM interview.interview_rounds WHERE id=:id"
            ),
            {"id": answer},
        ).one()
        assert result == ("1998年入学", 1, [])
        assert (
            db.scalar(
                text("SELECT source_revision FROM memory.memory_claims WHERE id=:id"), {"id": claim}
            )
            == 1
        )
    command.downgrade(config, "20260929_0040")
    with engine.connect() as db:
        assert (
            db.scalar(
                text("SELECT answer_text FROM interview.interview_rounds WHERE id=:id"),
                {"id": answer},
            )
            == "1998年入学"
        )
    command.upgrade(config, "head")
    command.check(config)

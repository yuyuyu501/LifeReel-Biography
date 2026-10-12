"""Additive migration and loss-preventing rollback on disposable PostgreSQL."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from test_service_schemas import postgres  # noqa: F401

from alembic import command


def test_strategy_upgrade_preserves_sessions_and_guards_state(postgres):  # noqa: F811
    target, config = postgres
    command.upgrade(config, "20261008_0044")
    ids = {key: uuid4() for key in ("tenant", "person", "session")}
    with target.begin() as db:
        db.execute(
            text("""INSERT INTO identity.tenants (id,name,slug,created_at)
            VALUES (:tenant,'Synthetic migration',:slug,now())"""),
            {**ids, "slug": str(ids["tenant"])},
        )
        db.execute(
            text("""INSERT INTO identity.persons
            (id,tenant_id,display_name,is_subject,is_minor,created_at,updated_at)
            VALUES (:person,:tenant,'Synthetic subject',true,false,now(),now())"""),
            ids,
        )
        db.execute(
            text("""INSERT INTO interview.interview_sessions
            (id,tenant_id,subject_id,status,round_count,started_at,created_at,updated_at)
            VALUES (:session,:tenant,:person,'active',0,now(),now(),now())"""),
            ids,
        )
    command.upgrade(config, "head")
    command.check(config)
    with target.begin() as db:
        assert (
            db.scalar(text("SELECT interview_state::text FROM interview.interview_sessions"))
            == "{}"
        )
        db.execute(
            text("UPDATE interview.interview_sessions SET interview_state=:state"),
            {"state": '{"action":"transition","blocked_quotes":["不想谈"]}'},
        )
    with pytest.raises(RuntimeError, match="export"):
        command.downgrade(config, "20261008_0044")
    with target.begin() as db:
        assert db.scalar(text("SELECT count(*) FROM interview.interview_sessions")) == 1
        db.execute(text("UPDATE interview.interview_sessions SET interview_state='{}'"))
    command.downgrade(config, "20261008_0044")
    command.upgrade(config, "head")
    command.check(config)

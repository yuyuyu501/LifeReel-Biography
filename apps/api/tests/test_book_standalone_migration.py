import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from test_service_schemas import postgres  # noqa: F401

from alembic import command


def test_standalone_upgrade_preserves_person_uniqueness_and_guards_rollback(postgres):  # noqa: F811
    target, config = postgres
    command.upgrade(config, "20261106_0047")
    with target.begin() as db:
        db.execute(text("""
            INSERT INTO identity.tenants (id,name,slug,created_at)
            VALUES ('00000000-0000-0000-0000-000000000048','QA','standalone-qa',now());
            INSERT INTO identity.persons
            (id,tenant_id,display_name,is_subject,is_minor,created_at,updated_at)
            VALUES ('00000000-0000-0000-0000-000000000049',
            '00000000-0000-0000-0000-000000000048','Synthetic',true,false,now(),now());
            INSERT INTO book.books (id,tenant_id,subject_id,title,created_at,updated_at)
            VALUES ('00000000-0000-0000-0000-000000000050',
            '00000000-0000-0000-0000-000000000048',
            '00000000-0000-0000-0000-000000000049','Existing book',now(),now())
        """))
    command.upgrade(config, "head")
    command.check(config)
    with target.begin() as db:
        assert db.scalar(text("SELECT title FROM book.books")) == "Existing book"
        db.execute(text("""
            INSERT INTO book.books (id,tenant_id,subject_id,title,created_at,updated_at)
            VALUES ('00000000-0000-0000-0000-000000000051',
            '00000000-0000-0000-0000-000000000048',null,'Standalone A',now(),now()),
            ('00000000-0000-0000-0000-000000000052',
            '00000000-0000-0000-0000-000000000048',null,'Standalone B',now(),now())
        """))
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(text("""
                INSERT INTO book.books (id,tenant_id,subject_id,title,created_at,updated_at)
                VALUES ('00000000-0000-0000-0000-000000000053',
                '00000000-0000-0000-0000-000000000048',
                '00000000-0000-0000-0000-000000000049','Duplicate',now(),now())
            """))
    with pytest.raises(RuntimeError, match="Standalone books exist"):
        command.downgrade(config, "20261106_0047")
    with target.begin() as db:
        assert db.scalar(text("SELECT count(*) FROM book.books")) == 3
        db.execute(text("DELETE FROM book.books WHERE subject_id IS NULL"))
    command.downgrade(config, "20261106_0047")
    column = next(c for c in inspect(target).get_columns("books", schema="book")
                  if c["name"] == "subject_id")
    assert column["nullable"] is False
    command.upgrade(config, "head")
    command.check(config)

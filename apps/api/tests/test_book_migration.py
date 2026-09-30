import pytest
from sqlalchemy import inspect, text
from test_service_schemas import postgres  # noqa: F401

from alembic import command


def test_books_upgrade_metadata_and_guarded_rollback(postgres):  # noqa: F811
    target, config = postgres
    command.upgrade(config, "20260930_0042")
    with target.begin() as db:
        db.execute(
            text("""INSERT INTO identity.tenants (id,name,slug,created_at)
            VALUES ('00000000-0000-0000-0000-000000000043','Book QA','book-qa',now())""")
        )
        db.execute(
            text("""INSERT INTO identity.persons
            (id,tenant_id,display_name,is_subject,is_minor,created_at,updated_at)
            VALUES ('00000000-0000-0000-0000-000000000044',
            '00000000-0000-0000-0000-000000000043','Synthetic',true,false,now(),now())""")
        )
    command.upgrade(config, "head")
    command.check(config)
    assert set(inspect(target).get_table_names(schema="book")) == {
        "books",
        "book_chapters",
        "book_revisions",
    }
    with target.begin() as db:
        db.execute(
            text("""INSERT INTO book.books
            (id,tenant_id,subject_id,title,created_at,updated_at) VALUES
            ('00000000-0000-0000-0000-000000000045',
            '00000000-0000-0000-0000-000000000043',
            '00000000-0000-0000-0000-000000000044','Synthetic book',now(),now())""")
        )
        assert db.scalar(text("SELECT target_words FROM book.books")) == 1000
    with pytest.raises(RuntimeError, match="Book data exists"):
        command.downgrade(config, "20260930_0042")
    with target.begin() as db:
        assert db.scalar(text("SELECT count(*) FROM book.books")) == 1
        db.execute(text("DELETE FROM book.books"))
    command.downgrade(config, "20260930_0042")
    assert "book" not in inspect(target).get_schema_names()
    command.upgrade(config, "head")
    command.check(config)

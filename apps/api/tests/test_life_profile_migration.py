"""Historical book preservation and non-destructive life-profile rollback guard."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from test_service_schemas import postgres  # noqa: F401

from alembic import command


def test_life_profile_upgrade_preserves_legacy_book_and_guards_new_data(postgres):  # noqa: F811
    target, config = postgres
    command.upgrade(config, "20260930_0043")
    ids = {
        name: uuid4() for name in ["tenant", "person", "chapter", "book", "book_chapter", "profile"]
    }
    with target.begin() as db:
        db.execute(
            text("""INSERT INTO identity.tenants (id,name,slug,created_at)
                    VALUES (:tenant,'Profile migration QA',:slug,now())"""),
            {**ids, "slug": str(ids["tenant"])},
        )
        db.execute(
            text("""INSERT INTO identity.persons
                    (id,tenant_id,display_name,is_subject,is_minor,created_at,updated_at)
                    VALUES (:person,:tenant,'Synthetic subject',true,false,now(),now())"""),
            ids,
        )
        db.execute(
            text("""INSERT INTO interview.chapters
                    (id,tenant_id,order_index,title,description,opening_questions,is_system,created_at)
                    VALUES (:chapter,:tenant,3,'Historical chapter',null,'[]',
                            false,now())"""),
            ids,
        )
        db.execute(
            text("""INSERT INTO book.books (id,tenant_id,subject_id,title,created_at,updated_at)
                    VALUES (:book,:tenant,:person,'Historical book',now(),now())"""),
            ids,
        )
        db.execute(
            text("""INSERT INTO book.book_chapters
                    (id,tenant_id,book_id,chapter_id,created_at,updated_at)
                    VALUES (:book_chapter,:tenant,:book,:chapter,now(),now())"""),
            ids,
        )
    command.upgrade(config, "head")
    command.check(config)
    with target.begin() as db:
        row = db.execute(
            text(
                "SELECT chapter_id,title,order_index,archived FROM book.book_chapters "
                "WHERE id=:book_chapter"
            ),
            ids,
        ).one()
        assert row == (ids["chapter"], "Historical chapter", 3, False)
        db.execute(
            text("""INSERT INTO interview.life_profiles
                    (id,tenant_id,subject_id,template_version,version_number,readiness,created_at,updated_at)
                    VALUES (:profile,:tenant,:person,'test',1,'{}',now(),now())"""),
            ids,
        )
    with pytest.raises(RuntimeError, match="Life profile data exists"):
        command.downgrade(config, "20260930_0043")
    with target.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM interview.life_profiles")) == 1
        assert db.scalar(text("SELECT version_num FROM public.alembic_version")) == "20261008_0044"


def test_profile_reads_and_book_creation_do_not_wait_on_foreign_key_lock(postgres, monkeypatch):  # noqa: F811
    from sqlalchemy.orm import Session

    from lifereel_api.modules.book import profile_sources
    from lifereel_api.modules.book import service as books
    from lifereel_api.modules.book.models import Book
    from lifereel_api.modules.book.schemas import BookCreate
    from lifereel_api.modules.identity.models import Person, Tenant
    from lifereel_api.modules.interview import profile_service

    target, config = postgres
    command.upgrade(config, "head")
    with Session(target) as db:
        tenant = Tenant(name="Lock regression", slug=str(uuid4()))
        db.add(tenant)
        db.flush()
        person = Person(tenant_id=tenant.id, display_name="Synthetic person")
        db.add(person)
        db.commit()
        tenant_id, person_id = tenant.id, person.id
        profile_id = profile_service.ensure(db, tenant_id, person_id).id
        db.commit()
    with Session(target) as writer, Session(target) as reader:
        writer.add(Book(tenant_id=tenant_id, subject_id=person_id, title="FK lock test"))
        writer.flush()
        reader.execute(text("SET LOCAL lock_timeout = '500ms'"))
        assert profile_service.ensure(reader, tenant_id, person_id).id == profile_id
        writer.rollback()
    # A new subject has no profile yet: the cross-service creation must run
    # before Book.flush() takes KEY SHARE on the person row.
    with Session(target) as db:
        person = Person(tenant_id=tenant_id, display_name="Another synthetic person")
        db.add(person)
        db.commit()
        person_id = person.id

        def independent_profile_read(_db, tenant, subject_id=None, **_kwargs):
            with Session(target) as remote:
                remote.execute(text("SET LOCAL lock_timeout = '500ms'"))
                profile = (
                    profile_service.ensure(remote, tenant, subject_id)
                    if subject_id else profile_service.get(remote, tenant, _kwargs["profile_id"])
                )
                result = profile_service.read(remote, tenant, profile.id)
                remote.commit()
                return result

        monkeypatch.setattr(profile_sources, "profile_read", independent_profile_read)
        book = books.create(db, tenant_id, BookCreate(subject_id=person_id))
        assert book.profile_id and len(book.chapters) == 1

        from lifereel_api.modules.interview.profile_schemas import ProfilePatch
        from lifereel_api.modules.memory.profile_sync import sync

        def independent_memory_sync(_db, tenant, profile_id):
            with Session(target) as remote:
                remote.execute(text("SET LOCAL lock_timeout = '500ms'"))
                return sync(remote, tenant, {"profile_id": str(profile_id)})

        monkeypatch.setattr(profile_service, "sync_memory", independent_memory_sync)
        profile = profile_service.read(db, tenant_id, book.profile_id)
        payload = ProfilePatch(
            expected_version=profile["version_number"],
            changes=[{"field_key": "values.self_description", "value": "仅为合成锁回归"}],
        )
        accepted = profile_service.patch(db, tenant_id, book.profile_id, payload)
        replayed = profile_service.patch(db, tenant_id, book.profile_id, payload)
        assert accepted["version_number"] == replayed["version_number"]

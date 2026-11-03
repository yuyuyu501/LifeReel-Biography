from uuid import UUID, uuid4

import pytest
from lifereel_api.modules.auth.dependencies import AuthContext, auth_context
from lifereel_api.modules.billing.models import Wallet
from lifereel_api.modules.book.models import BookChapter, BookRevision
from lifereel_api.modules.evidence.models import SourceAsset
from lifereel_api.modules.identity.deletion import delete_person
from lifereel_api.modules.identity.models import Person
from lifereel_api.modules.jobs.models import Job
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import Base, SessionLocal


def populated_person(client, name):
    person = client.post("/v1/persons", json={"display_name": name}).json()
    chapter = client.get("/v1/chapters").json()[0]
    session = client.post(
        "/v1/interviews",
        json={
            "mode": "legacy",
            "subject_id": person["id"],
            "chapter_id": chapter["id"],
        },
    ).json()
    answer = client.post(
        f"/v1/interviews/{session['id']}/rounds/{session['rounds'][0]['id']}/answer",
        json={"answer_text": "1958年我出生在苏州，母亲很会唱评弹。"},
    )
    assert answer.status_code == 200, answer.text
    assert (
        client.post(
            "/v1/memories/compile",
            json={
                "interview_session_id": session["id"],
            },
        ).status_code
        == 200
    )
    script = client.post(
        "/v1/scripts/generate",
        json={
            "subject_id": person["id"],
            "mode": "single_chapter",
            "audience": "family",
        },
    )
    assert script.status_code == 201, script.text
    run = client.post(
        "/v1/production/runs",
        json={
            "project_id": script.json()["id"],
            "audience": "family",
            "provider": "mock",
        },
    )
    assert run.status_code == 201, run.text
    book = client.post(
        "/v1/books",
        json={
            "source_mode": "legacy",
            "subject_id": person["id"],
            "title": name + "的书",
        },
    )
    assert book.status_code == 201, book.text
    with SessionLocal() as db:
        book_chapter = db.scalar(
            select(BookChapter).where(
                BookChapter.book_id == UUID(book.json()["id"]),
            )
        )
        db.add(
            BookRevision(
                tenant_id=book_chapter.tenant_id,
                book_chapter_id=book_chapter.id,
                version_number=1,
                title="合成书稿",
                body="合成正文",
                word_count=4,
                source_digest="0" * 64,
                author="human",
            )
        )
        db.commit()
    return person, session, script.json(), run.json(), book.json()


def test_delete_populated_person_preserves_other_family_and_finances(client):
    first = populated_person(client, "待删除合成人物")
    second = populated_person(client, "保留合成人物")
    tenant = get_settings().default_tenant_id
    with SessionLocal() as db:
        wallet_before = dict(db.execute(select(Wallet.__table__)).mappings().one())
        preserved = {}
        # Snapshot all rows belonging directly to the other person.
        for table in Base.metadata.sorted_tables:
            if "subject_id" in table.c:
                preserved[table] = list(
                    db.execute(
                        select(table).where(
                            table.c.subject_id == UUID(second[0]["id"]),
                        )
                    ).mappings()
                )
        counts = {}
        for table in Base.metadata.sorted_tables:
            if table.schema in {"billing", "model_gateway"}:
                counts[table] = list(db.execute(select(table)).mappings())
    response = client.delete(f"/v1/persons/{first[0]['id']}")
    assert response.status_code == 204, response.text
    assert response.content == b""
    assert client.get(f"/v1/persons/{first[0]['id']}").status_code == 404
    assert client.get(f"/v1/interviews/{first[1]['id']}").status_code == 404
    assert client.get(f"/v1/books/{first[4]['id']}").status_code == 404
    assert client.get(f"/v1/scripts/{first[2]['id']}").status_code == 404
    asset = first[3]["assets"][0]["id"]
    assert client.get(f"/v1/production/assets/{asset}/content").status_code == 404
    for path in (
        f"/v1/persons/{second[0]['id']}",
        f"/v1/books/{second[4]['id']}",
        f"/v1/interviews/{second[1]['id']}",
    ):
        assert client.get(path).status_code == 200
    with SessionLocal() as db:
        for table, before in preserved.items():
            assert (
                list(
                    db.execute(
                        select(table).where(
                            table.c.subject_id == UUID(second[0]["id"]),
                        )
                    ).mappings()
                )
                == before
            )
        for table, before in counts.items():
            assert list(db.execute(select(table)).mappings()) == before
        assert dict(db.execute(select(Wallet.__table__)).mappings().one()) == wallet_before
        jobs = list(db.scalars(select(Job).where(Job.tenant_id == tenant)))
        retired = [job for job in jobs if job.error_code == "PERSON_DELETED"]
        assert retired
        for job in retired:
            assert client.post(f"/v1/jobs/{job.id}/retry").status_code == 409
    assert client.delete(f"/v1/persons/{first[0]['id']}").status_code == 404


def test_delete_empty_last_person_and_tenant_isolation(client):
    person = client.post("/v1/persons", json={"display_name": "合成人物"}).json()
    denied = client.delete(f"/v1/persons/{person['id']}", headers={"X-Tenant-ID": str(uuid4())})
    assert denied.status_code == 404
    assert client.get(f"/v1/persons/{person['id']}").status_code == 200
    assert client.delete(f"/v1/persons/{person['id']}").status_code == 204
    assert client.get("/v1/persons").json() == []


@pytest.mark.parametrize("role", ["viewer"])
def test_viewer_cannot_delete(client, role):
    from lifereel_api.main import app

    person = client.post("/v1/persons", json={"display_name": "只读测试"}).json()
    app.dependency_overrides[auth_context] = lambda: AuthContext(
        None,
        get_settings().default_tenant_id,
        role,
    )
    try:
        assert client.delete(f"/v1/persons/{person['id']}").status_code == 403
    finally:
        app.dependency_overrides.pop(auth_context)
    assert client.get(f"/v1/persons/{person['id']}").status_code == 200


@pytest.mark.parametrize("status", ["queued", "running"])
def test_active_job_blocks_deletion_without_partial_changes(client, status):
    person = client.post("/v1/persons", json={"display_name": "繁忙测试"}).json()
    with SessionLocal() as db:
        db.add(
            Job(
                tenant_id=get_settings().default_tenant_id,
                kind="book.generate",
                status=status,
                payload={"subject_id": person["id"]},
            )
        )
        db.commit()
    response = client.delete(f"/v1/persons/{person['id']}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PERSON_DELETE_BUSY"
    assert client.get(f"/v1/persons/{person['id']}").status_code == 200


def test_set_null_reference_does_not_delete_another_person_asset(client):
    first = client.post("/v1/persons", json={"display_name": "原图人物"}).json()
    second = client.post("/v1/persons", json={"display_name": "派生图人物"}).json()
    with SessionLocal() as db:
        original = SourceAsset(
            tenant_id=get_settings().default_tenant_id,
            subject_id=UUID(first["id"]),
            kind="image",
            original_filename="synthetic.png",
            mime_type="image/png",
            byte_size=1,
            sha256="1" * 64,
            storage_key="synthetic/original",
        )
        db.add(original)
        db.flush()
        derived = SourceAsset(
            tenant_id=original.tenant_id,
            subject_id=UUID(second["id"]),
            kind="image",
            original_filename="synthetic-derived.png",
            mime_type="image/png",
            byte_size=1,
            sha256="2" * 64,
            storage_key="synthetic/derived",
            derived_from_asset_id=original.id,
        )
        db.add(derived)
        db.commit()
        derived_id = derived.id
    assert client.delete(f"/v1/persons/{first['id']}").status_code == 204
    with SessionLocal() as db:
        assert db.get(SourceAsset, derived_id).derived_from_asset_id is None
        assert db.get(Person, UUID(second["id"])) is not None


def test_failure_rolls_back_all_deleted_records(client, monkeypatch):
    from lifereel_api.modules.identity import deletion

    person = client.post("/v1/persons", json={"display_name": "回滚测试"}).json()
    monkeypatch.setattr(
        deletion,
        "audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("synthetic audit failure"),
        ),
    )
    with SessionLocal() as db:
        with pytest.raises(RuntimeError):
            delete_person(db, get_settings().default_tenant_id, UUID(person["id"]))
        db.rollback()
    assert client.get(f"/v1/persons/{person['id']}").status_code == 200

"""Use the whole permitted theme, without expanding the owner's explicit selection."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.billing.models import Charge
from lifereel_api.modules.book import writing
from lifereel_api.modules.book.models import BookChapter
from lifereel_api.modules.jobs.dispatch import claim_job, execute_claim
from lifereel_api.modules.jobs.models import Job
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


def patch(client, profile, changes):
    response = client.patch(f"/v1/life-profiles/{profile['id']}", json={
        "expected_version": profile["version_number"], "changes": changes,
        "request_id": str(uuid4()),
    })
    assert response.status_code == 200, response.text
    return response.json()


def event(title):
    return {
        "title": title, "what": "这是具体经历中的事情，记录当时发生的真实经过。" * 4,
        "action": "我每天整理家里的物品，并主动帮助家人。",
        "impact": "这让我学会承担责任，也保留了共同生活的记忆。",
    }


@pytest.fixture
def materials(client):
    person = client.post("/v1/persons", json={"display_name": "选材回归人物"}).json()
    profile = client.get(f"/v1/life-profiles/subjects/{person['id']}").json()
    profile = patch(client, profile, [
        {"field_key": "family.home_environment", "value": event("家庭环境")},
        {"field_key": "family.household", "value": "我们一家人共同生活。"},
        {"field_key": "family.origin", "value": "家庭来自一个小村庄。"},
        {"field_key": "family.livelihood", "value": "父母靠务农维持生计。"},
        {"field_key": "family.traditions", "value": "家人重视认真做事。"},
        {"field_key": "family.members[]", "record_key": "public", "value": {
            "name": "甲姓名", "relationship": "父亲", "story": "父亲教我修理木凳。",
        }, "use_scope": "pseudonym", "pseudonyms": {"甲姓名": "父亲甲"}},
        *[
            {"field_key": "family.members[]", "record_key": state,
             "value": "不应该进入书稿的资料", **overrides}
            for state, overrides in [
                ("private", {"use_scope": "internal"}),
                ("pending", {"certainty": "pending"}),
                ("disputed", {"certainty": "disputed"}),
                ("unknown", {"state": "unknown"}),
                ("declined", {"state": "declined"}),
            ]
        ],
        {"field_key": "work.events[]", "record_key": "work", "value": event("工作经历")},
        {"field_key": "work.meaning", "value": "我学会了耐心核对工作记录。"},
    ])
    response = client.post("/v1/books", json={"subject_id": person["id"]})
    assert response.status_code == 201, response.text
    return profile, response.json()


def family(book):
    return next(ch for ch in book["chapters"] if ch["title"] == "家庭与成长背景")


def read(client, book):
    return client.get(f"/v1/books/{book['id']}").json()


def queue(client, book):
    response = client.post(f"/v1/books/{book['id']}/generate", json={
        "idempotency_key": str(uuid4()), "chapter_ids": [family(book)["id"]],
    })
    assert response.status_code == 202, response.text
    return response.json()["job_ids"][0]


def run(monkeypatch):
    monkeypatch.setattr(get_settings(), "job_queue_backend", "database")
    with SessionLocal() as db:
        claim = claim_job(db, "book")
        assert claim is not None
        return execute_claim(db, UUID(claim["job_id"]), UUID(claim["token"]))


def test_default_chapter_passes_all_theme_fields_and_excludes_restricted_material(
    client, materials, monkeypatch,
):
    profile, book = materials
    chapter = family(book)
    assert chapter["source_count"] == 6
    assert len(chapter["source_entry_ids"]) == 6
    job_id = queue(client, book)
    captured = []

    def generate(snapshot):
        captured.append(snapshot)
        return {"title": snapshot["chapter"], "body": "合成正文" * 250, "word_count": 1000,
                "source_claim_ids": [c["id"] for c in snapshot["claims"]]}

    monkeypatch.setattr(writing, "generate", generate)
    assert run(monkeypatch)["status"] == "completed"
    claims = captured[0]["claims"]
    assert len(claims) == 6
    assert all(c["field_key"].startswith("family.") for c in claims)
    assert "甲姓名" not in str(claims) and "父亲甲" in str(claims)
    assert "不应该进入书稿" not in str(claims)
    assert set(c["id"] for c in claims) == set(chapter["source_entry_ids"])
    with SessionLocal() as db:
        assert db.get(Job, UUID(job_id)).status == "completed"


def test_old_default_book_is_expanded_on_read_without_writing_or_rebuilding(client, materials):
    profile, book = materials
    representative = next(e for e in profile["entries"]
                          if e["field_key"] == "family.home_environment")["id"]
    with SessionLocal() as db:
        db.get(BookChapter, UUID(family(book)["id"])).source_entry_ids = [representative]
        db.commit()
    updated = read(client, book)
    assert family(updated)["source_count"] == 6
    assert len(family(updated)["source_entry_ids"]) == 6
    with SessionLocal() as db:
        assert db.get(BookChapter, UUID(family(book)["id"])).source_entry_ids == [representative]


def test_later_theme_entries_are_added_but_manual_selection_is_preserved(client, materials):
    profile, book = materials
    profile = patch(client, profile, [{
        "field_key": "family.members[]", "record_key": "new", "value": "姐姐常帮助我读书。",
    }])
    assert family(read(client, book))["source_count"] == 7
    selected = family(book)["source_entry_ids"][:1]
    edited = client.patch(f"/v1/books/{book['id']}/directory", json={
        "expected_version": book["directory_version"], "title": book["title"],
        "chapters": [{"id": family(book)["id"], "title": family(book)["title"],
                      "source_entry_ids": selected}],
    })
    assert edited.status_code == 200, edited.text
    assert family(edited.json())["source_count"] == 1
    profile = patch(client, profile, [{
        "field_key": "family.members[]", "record_key": "newer", "value": "弟弟喜欢修理物品。",
    }])
    reopened = client.post("/v1/books", json={"subject_id": book["subject_id"]}).json()
    assert len(reopened["chapters"]) == 1
    assert family(reopened)["source_entry_ids"] == selected


def test_default_directory_does_not_drop_last_two_of_ten_themes(client):
    person = client.post("/v1/persons", json={"display_name": "十主题人物"}).json()
    profile = client.get(f"/v1/life-profiles/subjects/{person['id']}").json()
    keys = [next(f["key"] for f in profile["fields"]
                 if f["section"] == section and not f["key"].endswith(".applicability"))
            for section in "BCDEFGHIJK"]
    patch(client, profile, [{"field_key": key, "value": event(key)} for key in keys])
    book = client.post("/v1/books", json={"subject_id": person["id"]}).json()
    assert len(book["chapters"]) == 10
    first_ids = [c["id"] for c in book["chapters"][:8]]
    job_id = queue(client, book)
    with SessionLocal() as db:
        for chapter in book["chapters"][8:]:
            db.delete(db.get(BookChapter, UUID(chapter["id"])))
        db.commit()
    busy = client.post("/v1/books", json={"subject_id": person["id"]}).json()
    assert len(busy["chapters"]) == 8
    with SessionLocal() as db:
        db.get(Job, UUID(job_id)).status = "failed"
        db.commit()
    reopened = client.post("/v1/books", json={"subject_id": person["id"]}).json()
    assert len(reopened["chapters"]) == 10
    assert [c["id"] for c in reopened["chapters"][:8]] == first_ids
    again = client.post("/v1/books", json={"subject_id": person["id"]}).json()
    assert [c["id"] for c in again["chapters"]] == [c["id"] for c in reopened["chapters"]]


def test_material_questions_survive_failure_and_become_obsolete_after_profile_changes(
    client, materials, monkeypatch,
):
    profile, book = materials
    settings = get_settings()
    for name, value in {
        "llm_provider": "openai-compatible",
        "openai_compatible_base_url": "https://model.invalid/v1",
        "openai_compatible_api_key": "synthetic", "script_llm_model": "synthetic",
    }.items():
        monkeypatch.setattr(settings, name, value)
    questions = ["家人如何分担家务？", "请讲一件体现家风的事情。"]
    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", lambda *args: {
        "material_sufficient": False, "title": "家庭", "outline": [], "paragraphs": [],
        "missing_details": questions,
    })
    job_id = queue(client, book)
    assert run(monkeypatch)["status"] == "failed"
    current = family(read(client, book))
    assert current["error_code"] == "BOOK_MATERIAL_INSUFFICIENT"
    assert current["missing_details"] == questions
    with SessionLocal() as db:
        assert db.scalar(select(Charge).where(Charge.kind == "book")).status == "released"
    patch(client, profile, [{
        "field_key": "family.traditions", "value": "父亲每年教我们修好旧木凳。",
    }])
    updated = family(read(client, book))
    assert updated["error_code"] == "BOOK_MATERIAL_UPDATED"
    assert updated["missing_details"] == []
    with SessionLocal() as db:
        assert db.get(Job, UUID(job_id)).error_code == "BOOK_MATERIAL_INSUFFICIENT"

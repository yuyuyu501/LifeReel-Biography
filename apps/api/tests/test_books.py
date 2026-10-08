import copy
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing.models import Charge
from lifereel_api.modules.book import service, writing
from lifereel_api.modules.book.models import BookRevision
from lifereel_api.modules.book.schemas import BookCreate
from lifereel_api.modules.identity.models import Person, Tenant
from lifereel_api.modules.jobs.dispatch import claim_job, execute_claim
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.memory.models import MemoryClaim, MemoryConflict
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


@pytest.fixture
def book(client):
    person = client.post("/v1/persons", json={"display_name": "书稿测试人物"}).json()
    chapters = client.get("/v1/chapters").json()
    result = client.post(
        "/v1/books",
        json={"source_mode": "legacy", "subject_id": person["id"], "title": "合成人生书"},
    )
    assert result.status_code == 201, result.text
    return {
        "book": result.json(),
        "subject": person,
        "chapter": chapters[0],
        "other_chapter": chapters[1],
        "tenant": get_settings().default_tenant_id,
    }


def add_fact(book, **overrides):
    with SessionLocal() as db:
        row = MemoryClaim(
            tenant_id=book["tenant"],
            subject_id=UUID(book["subject"]["id"]),
            chapter_id=UUID(book["chapter"]["id"]),
            claim_text="1992年在泉州入学，此后学习书法。",
            source_quote="原始合成采访",
        )
        for key, value in overrides.items():
            setattr(row, key, value)
        db.add(row)
        db.commit()
        return row.id


def generated(snapshot):
    text = ("合成测试文字" * 200)[:1000]
    return {
        "title": snapshot["chapter"],
        "body": text,
        "word_count": writing.word_count(text),
        "source_claim_ids": [snapshot["claims"][0]["id"]],
    }


def queue(client, book, **overrides):
    payload = {
        "idempotency_key": str(uuid4()),
        "chapter_ids": [book["chapter"]["id"]],
        "overwrite": True,
        **overrides,
    }
    response = client.post("/v1/books/" + book["book"]["id"] + "/generate", json=payload)
    return response, payload


def run_job(monkeypatch):
    monkeypatch.setattr(get_settings(), "job_queue_backend", "database")
    with SessionLocal() as db:
        claim = claim_job(db, "book")
        assert claim is not None
        return execute_claim(db, UUID(claim["job_id"]), UUID(claim["token"]))


def read(client, book):
    return client.get("/v1/books/" + book["book"]["id"]).json()


def test_create_list_and_reopen_preserves_existing_book(client, book):
    again = client.post(
        "/v1/books",
        json={"source_mode": "legacy", "subject_id": book["subject"]["id"], "title": "另一个标题"},
    )
    assert again.json()["id"] == book["book"]["id"]
    assert again.json()["title"] == "合成人生书"
    assert len(client.get("/v1/books").json()) == 1
    assert read(client, book)["target_words"] == 1000


def test_empty_sources_do_not_queue_or_charge(client, book):
    response, _ = queue(client, book)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BOOK_MATERIAL_INSUFFICIENT"
    assert client.get("/v1/books/" + book["book"]["id"] + "/export").status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 0
        assert db.scalar(select(func.count()).select_from(Charge)) == 0


def test_generation_persists_and_duplicate_request_settles_once(client, book, monkeypatch):
    add_fact(book)
    calls = []
    monkeypatch.setattr(writing, "generate", lambda data: (calls.append(data), generated(data))[1])
    response, payload = queue(client, book)
    assert response.status_code == 202, response.text
    assert queue(client, book, **payload)[0].json() == response.json()
    assert run_job(monkeypatch)["status"] == "completed"
    data = read(client, book)["chapters"][0]
    assert data["current"]["word_count"] == 1000
    assert data["version_number"] == 1 and not data["stale"]
    with SessionLocal() as db:
        service.execute(db, book["tenant"], UUID(response.json()["job_ids"][0]))
        charges = list(db.scalars(select(Charge).where(Charge.kind == "book")))
        assert len(charges) == 1 and charges[0].status == "settled"
        assert db.scalar(select(func.count()).select_from(BookRevision)) == 1
    assert len(calls) == 1
    exported = client.get("/v1/books/" + book["book"]["id"] + "/export?format=md")
    assert exported.status_code == 200 and data["current"]["body"] in exported.text
    assert "attachment" in exported.headers["content-disposition"]


def test_conflicting_request_and_active_regeneration_rejected(client, book):
    add_fact(book)
    first, payload = queue(client, book)
    assert first.status_code == 202
    altered, _ = queue(client, book, **{**payload, "overwrite": False})
    assert altered.status_code == 409
    assert altered.json()["error"]["code"] == "BOOK_REQUEST_CONFLICT"
    assert queue(client, book)[0].json()["error"]["code"] == "BOOK_GENERATION_BUSY"


def test_all_chapters_queue_only_supported_material(client, book):
    add_fact(book)
    response = client.post(
        "/v1/books/" + book["book"]["id"] + "/generate", json={"idempotency_key": str(uuid4())}
    )
    assert response.status_code == 202
    assert len(response.json()["job_ids"]) == 1
    assert book["other_chapter"]["id"] in response.json()["skipped_chapter_ids"]


@pytest.mark.parametrize("review_status", ["private", "disputed", "superseded"])
def test_private_and_disputed_material_not_used(client, book, review_status):
    add_fact(book, review_status=review_status)
    assert queue(client, book)[0].status_code == 409


def test_unresolved_conflicts_exclude_sources(client, book):
    claim = add_fact(book)
    with SessionLocal() as db:
        db.add(
            MemoryConflict(
                tenant_id=book["tenant"],
                subject_id=UUID(book["subject"]["id"]),
                claim_ids=[str(claim)],
                conflict_key="year",
                description="合成冲突",
            )
        )
        db.commit()
    assert queue(client, book)[0].status_code == 409


def test_corrected_facts_are_used_and_later_changes_mark_stale(client, book, monkeypatch):
    claim = add_fact(
        book,
        fact_overrides=[
            {
                "target_revision": 1,
                "old_text": "泉州",
                "new_text": "福州",
                "correction_claim_id": str(uuid4()),
                "evidence_quote": "正确的是福州",
            }
        ],
    )
    captured = []
    monkeypatch.setattr(
        writing, "generate", lambda data: (captured.append(data), generated(data))[1]
    )
    queue(client, book)
    assert run_job(monkeypatch)["status"] == "completed"
    assert "福州" in captured[0]["claims"][0]["claim_text"]
    assert captured[0]["claims"][0]["source_quote"] == ""
    with SessionLocal() as db:
        db.get(MemoryClaim, claim).claim_text += "毕业后学习木工。"
        db.commit()
    assert read(client, book)["chapters"][0]["stale"] is True


def test_source_change_before_execution_avoids_model_and_charge(client, book, monkeypatch):
    claim = add_fact(book)
    queue(client, book)
    with SessionLocal() as db:
        db.get(MemoryClaim, claim).claim_text += "更新事实"
        db.commit()
    monkeypatch.setattr(writing, "generate", lambda _: pytest.fail("must not call model"))
    assert run_job(monkeypatch)["status"] == "failed"
    row = read(client, book)["chapters"][0]
    assert row["error_code"] == "BOOK_SOURCE_CHANGED" and row["current"] is None


@pytest.mark.parametrize("failure", ["invalid", "insufficient", "source_changed"])
def test_failed_rewrite_keeps_prior_revision_and_releases_hold(client, book, monkeypatch, failure):
    claim = add_fact(book)
    monkeypatch.setattr(writing, "generate", generated)
    queue(client, book)
    assert run_job(monkeypatch)["status"] == "completed"
    old = read(client, book)["chapters"][0]["current"]

    def fail(snapshot):
        if failure == "source_changed":
            with SessionLocal() as db:
                db.get(MemoryClaim, claim).claim_text += "生成过程中更正了事实。"
                db.commit()
            return generated(snapshot)
        raise ApiError(
            502,
            ErrorCode.BOOK_OUTPUT_INVALID
            if failure == "invalid"
            else ErrorCode.BOOK_MATERIAL_INSUFFICIENT,
        )

    monkeypatch.setattr(writing, "generate", fail)
    queue(client, book)
    assert run_job(monkeypatch)["status"] == "failed"
    assert read(client, book)["chapters"][0]["current"] == old
    with SessionLocal() as db:
        statuses = list(db.scalars(select(Charge.status).where(Charge.kind == "book")))
        assert sorted(statuses) == ["released", "settled"]


def test_manual_edit_versions_conflicts_and_history(client, book, monkeypatch):
    add_fact(book)
    monkeypatch.setattr(writing, "generate", generated)
    queue(client, book)
    run_job(monkeypatch)
    url = "/v1/books/" + book["book"]["id"] + "/chapters/" + book["chapter"]["id"]
    payload = {"expected_version": 1, "title": "用户调整的章名", "body": "用户自己编辑的正文。"}
    result = client.patch(url, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["chapters"][0]["version_number"] == 2
    assert client.patch(url, json=payload).status_code == 409
    history = client.get(url + "/versions").json()
    assert [r["version_number"] for r in history] == [2, 1]
    assert history[0]["author"] == "user" and history[1]["word_count"] == 1000


def test_cross_tenant_book_and_chapter_access_is_denied(client, book):
    with SessionLocal() as db:
        tenant = Tenant(name="其他家庭", slug=uuid4().hex)
        db.add(tenant)
        db.flush()
        person = Person(tenant_id=tenant.id, display_name="不可见人物")
        db.add(person)
        db.commit()
        other = service.create(db, tenant.id, BookCreate(subject_id=person.id))
        hidden_id = other.id
        with pytest.raises(ApiError) as exc:
            service.read(db, tenant.id, UUID(book["book"]["id"]))
        assert exc.value.code == ErrorCode.BOOK_NOT_FOUND
    for suffix in ("", "/export", "/chapters/" + book["chapter"]["id"] + "/versions"):
        assert client.get("/v1/books/" + str(hidden_id) + suffix).status_code == 404
    assert (
        client.post(
            "/v1/books/" + str(hidden_id) + "/generate",
            json={
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 404
    )


@pytest.mark.parametrize("bad", ["short", "long", "foreign_source", "duplicate", "empty_outline"])
def test_generated_output_validation(bad):
    output = {
        "material_sufficient": True,
        "title": "合成章节",
        "outline": ["合成事实"],
        "paragraphs": [{"text": "字" * 1000, "source_claim_ids": ["known"]}],
        "missing_details": [],
    }
    if bad in {"short", "long"}:
        output["paragraphs"][0]["text"] = "字" * (899 if bad == "short" else 1101)
    elif bad == "foreign_source":
        output["paragraphs"][0]["source_claim_ids"] = ["foreign"]
    elif bad == "duplicate":
        output["paragraphs"][0]["text"] = "字" * 500
        output["paragraphs"].append(copy.deepcopy(output["paragraphs"][0]))
    else:
        output["outline"] = []
    with pytest.raises(ValueError):
        writing.validate_output(output, {"claims": [{"id": "known"}]})


def test_writer_performs_bounded_repair_without_external_calls(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openai-compatible")
    monkeypatch.setattr(settings, "openai_compatible_base_url", "https://synthetic.test/v1")
    monkeypatch.setattr(settings, "openai_compatible_api_key", "synthetic")
    monkeypatch.setattr(settings, "script_llm_model", "synthetic")
    captured = []

    def model(self, system, user):
        captured.append((system, json.loads(user)))
        return {
            "material_sufficient": True,
            "title": "测试",
            "outline": ["真实来源"],
            "paragraphs": [
                {"text": "字" * (1000 if len(captured) == 2 else 5), "source_claim_ids": ["known"]}
            ],
            "missing_details": [],
        }

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", model)
    result = writing.generate({"claims": [{"id": "known", "claim_text": "已纠正的事实"}]})
    assert result["word_count"] == 1000 and len(captured) == 2
    assert "不得虚构" in captured[0][0] and "上次输出" in captured[1][0]


def test_word_count_omits_spacing_and_punctuation():
    assert writing.word_count("汉字，AB 12！\n") == 6

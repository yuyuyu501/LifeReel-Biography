from uuid import UUID, uuid4

import pytest
from lifereel_api.modules.book import service
from lifereel_api.modules.book.fact_check import _validate_findings
from lifereel_api.modules.book.models import BookChapter, BookFactCheck, BookRevision
from lifereel_api.modules.jobs.dispatch import claim_job, execute_claim
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.memory.models import MemoryClaim
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal


@pytest.fixture
def book_with_revisions(client):
    person = client.post("/v1/persons", json={"display_name": "事实核查合成人物"}).json()
    chapters = client.get("/v1/chapters").json()
    book = client.post(
        "/v1/books",
        json={
            "source_mode": "legacy",
            "subject_id": person["id"],
            "title": "事实核查测试书",
        },
    ).json()
    tenant = get_settings().default_tenant_id
    revisions = []
    with SessionLocal() as db:
        book_row = service.get_book(db, tenant, UUID(book["id"]))
        for chapter, fact, body in [
            (chapters[0], "1992年在泉州入学。", "我在1990年开始上学。"),
            (chapters[1], "1994年在厦门入学。", "我在1994年在厦门入学。"),
        ]:
            claim = MemoryClaim(
                tenant_id=tenant,
                subject_id=UUID(person["id"]),
                chapter_id=UUID(chapter["id"]),
                claim_text=fact,
                source_quote=f"原始记录：{fact}",
            )
            db.add(claim)
            db.flush()
            chapter_row = db.scalar(
                select(BookChapter).where(
                    BookChapter.book_id == book_row.id,
                    BookChapter.chapter_id == UUID(chapter["id"]),
                )
            )
            snapshot = service.source(db, book_row, UUID(chapter["id"]))
            chapter_row.version_number = 1
            revision = BookRevision(
                tenant_id=tenant,
                book_chapter_id=chapter_row.id,
                version_number=1,
                title=chapter["title"],
                body=body,
                word_count=len(body),
                source_digest=service.digest(snapshot),
                source_snapshot=snapshot,
                source_claim_ids=[str(claim.id)],
                author="user",
                generation_model=None,
            )
            db.add(revision)
            db.flush()
            revisions.append(
                {
                    "chapter_id": chapter["id"],
                    "chapter_title": chapter["title"],
                    "revision_id": str(revision.id),
                    "claim_id": str(claim.id),
                    "fact": fact,
                    "body": body,
                }
            )
        db.commit()
    return {
        "book": book,
        "subject": person,
        "chapters": chapters,
        "revisions": revisions,
        "tenant": tenant,
    }


def run_fact_check(monkeypatch):
    monkeypatch.setattr(get_settings(), "job_queue_backend", "database")
    with SessionLocal() as db:
        claim = claim_job(db, "book")
        assert claim is not None
        return execute_claim(db, UUID(claim["job_id"]), UUID(claim["token"]))


def make_findings(book):
    first, second = book["revisions"]
    return {
        "findings": [
            {
                "type": "conflict",
                "chapter_id": first["chapter_id"],
                "book_quote": first["body"],
                "explanation": "资料记载的入学年份不同。",
                "evidence": [
                    {
                        "kind": "source",
                        "chapter_id": first["chapter_id"],
                        "claim_id": str(first["claim_id"]),
                        "quote": first["fact"],
                        "revision_id": None,
                    }
                ],
            },
            {
                "type": "cross_chapter",
                "chapter_id": second["chapter_id"],
                "book_quote": second["body"],
                "explanation": "另一章的同一经历年份不同。",
                "evidence": [
                    {
                        "kind": "chapter",
                        "chapter_id": first["chapter_id"],
                        "claim_id": None,
                        "revision_id": str(first["revision_id"]),
                        "quote": first["body"],
                    }
                ],
            },
        ]
    }


def configure_fake_model(monkeypatch, output):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openai-compatible")
    monkeypatch.setattr(settings, "openai_compatible_base_url", "https://synthetic.test/v1")
    monkeypatch.setattr(settings, "openai_compatible_api_key", "synthetic")
    monkeypatch.setattr(settings, "script_llm_model", "synthetic-script")

    class FakeClient:
        last_model_used = "synthetic-script"

        def __init__(self, *_args, **_kwargs):
            pass

        def capabilities(self):
            return type("Capabilities", (), {"configured": True})()

        def chat_json(self, _prompt, _material):
            return output

    monkeypatch.setattr("lifereel_api.modules.book.fact_check.OpenAICompatibleClient", FakeClient)


def queue_fact_check(client, book, key=None):
    return client.post(
        f"/v1/books/{book['book']['id']}/fact-checks",
        json={"idempotency_key": str(key or uuid4())},
    )


def test_fact_check_queues_once_and_returns_grounded_findings(
    client, book_with_revisions, monkeypatch
):
    book = book_with_revisions
    configure_fake_model(monkeypatch, make_findings(book))
    key = uuid4()
    first = queue_fact_check(client, book, key)
    assert first.status_code == 202, first.text
    assert first.json()["status"] == "queued"
    assert queue_fact_check(client, book, key).json()["id"] == first.json()["id"]
    assert run_fact_check(monkeypatch)["status"] == "completed"

    latest = client.get(f"/v1/books/{book['book']['id']}/fact-checks/latest")
    assert latest.status_code == 200, latest.text
    result = latest.json()
    assert result["status"] == "completed"
    assert result["chapters_checked"] == 2
    assert [
        (row["chapter_id"], row["version_number"])
        for row in result["snapshot_chapters"]
    ] == [(row["chapter_id"], 1) for row in book["revisions"]]
    assert all(len(row["source_digest"]) == 64 for row in result["snapshot_chapters"])
    assert [row["type"] for row in result["findings"]] == ["conflict", "cross_chapter"]
    assert result["findings"][0]["evidence"][0]["quote"] == book["revisions"][0]["fact"]
    assert result["findings"][1]["evidence"][0]["revision_id"] == str(
        book["revisions"][0]["revision_id"]
    )
    assert client.get(f"/v1/jobs/{result['job_id']}").status_code == 404
    listed_jobs = client.get("/v1/jobs").json()
    assert all(row["id"] != result["job_id"] for row in listed_jobs)
    with SessionLocal() as db:
        charge = db.scalar(select(Job).where(Job.kind == "book.fact_check"))
        assert charge is not None and charge.status == "completed"
        report = db.get(BookFactCheck, UUID(result["id"]))
        assert report.status == "completed"
        assert report.findings[0]["chapter_title"] == book["chapters"][0]["title"]


def test_invalid_model_quote_fails_instead_of_reporting_clean(
    client, book_with_revisions, monkeypatch
):
    book = book_with_revisions
    output = make_findings(book)
    output["findings"][0]["book_quote"] = "模型编造的句子"
    configure_fake_model(monkeypatch, output)
    queued = queue_fact_check(client, book)
    assert queued.status_code == 202
    assert run_fact_check(monkeypatch)["status"] == "failed"
    latest = client.get(f"/v1/books/{book['book']['id']}/fact-checks/latest").json()
    assert latest["status"] == "failed"
    assert latest["error_code"] == "BOOK_CHECK_OUTPUT_INVALID"
    assert latest["findings"] == []


def test_fact_check_marks_changed_inputs_stale_without_model_call(
    client, book_with_revisions, monkeypatch
):
    book = book_with_revisions
    configure_fake_model(monkeypatch, make_findings(book))
    queued = queue_fact_check(client, book)
    assert queued.status_code == 202
    with SessionLocal() as db:
        claim = db.get(MemoryClaim, UUID(str(book["revisions"][0]["claim_id"])))
        claim.claim_text = "1993年在泉州入学。"
        db.commit()
    assert run_fact_check(monkeypatch)["status"] == "completed"
    latest = client.get(f"/v1/books/{book['book']['id']}/fact-checks/latest").json()
    assert latest["status"] == "stale"
    assert latest["stale"] is True
    assert latest["findings"] == []
    with SessionLocal() as db:
        assert db.scalar(select(Job).where(Job.kind == "book.fact_check")).status == "completed"
        assert not db.scalar(select(BookFactCheck).where(BookFactCheck.status == "failed"))


def test_fact_check_rejects_unverified_evidence_reference(book_with_revisions):
    snapshot = {
        "chapters": [
            {
                "chapter_id": row["chapter_id"],
                "chapter_title": row["chapter_title"],
                "revision_id": str(row["revision_id"]),
                "title": row["chapter_title"],
                "body": row["body"],
                "claims": [{"id": str(row["claim_id"]), "text": row["fact"]}],
            }
            for row in book_with_revisions["revisions"]
        ]
    }
    output = make_findings(book_with_revisions)
    output["findings"][0]["evidence"][0]["claim_id"] = str(uuid4())
    with pytest.raises(ValueError, match="invalid_source_quote"):
        _validate_findings(output, snapshot)


def test_fact_check_does_not_queue_with_private_source_claim(client, book_with_revisions):
    book = book_with_revisions
    with SessionLocal() as db:
        claim = db.get(MemoryClaim, UUID(str(book["revisions"][0]["claim_id"])))
        claim.review_status = "private"
        db.commit()
    response = queue_fact_check(client, book)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BOOK_SOURCE_CHANGED"
    with SessionLocal() as db:
        assert db.scalar(select(Job).where(Job.kind == "book.fact_check")) is None


def test_fact_check_rejects_quotes_joining_title_and_body(book_with_revisions):
    book = book_with_revisions
    first, second = book["revisions"]
    snapshot = {
        "chapters": [
            {
                "chapter_id": row["chapter_id"],
                "chapter_title": row["chapter_title"],
                "revision_id": str(row["revision_id"]),
                "title": row["chapter_title"],
                "body": row["body"],
                "claims": [{"id": str(row["claim_id"]), "text": row["fact"]}],
            }
            for row in book["revisions"]
        ]
    }
    output = {
        "findings": [
            {
                "type": "unsupported",
                "chapter_id": first["chapter_id"],
                "book_quote": first["body"] + second["chapter_title"],
                "explanation": "合成测试",
                "evidence": [],
            }
        ]
    }
    with pytest.raises(ValueError, match="invalid_book_quote"):
        _validate_findings(output, snapshot)


def test_fact_check_finding_can_be_marked_false_positive(
    client, book_with_revisions, monkeypatch
):
    book = book_with_revisions
    configure_fake_model(monkeypatch, make_findings(book))
    queued = queue_fact_check(client, book)
    assert queued.status_code == 202
    assert run_fact_check(monkeypatch)["status"] == "completed"
    report = client.get(f"/v1/books/{book['book']['id']}/fact-checks/latest").json()
    finding_id = report["findings"][0]["id"]
    response = client.patch(
        f"/v1/books/{book['book']['id']}/fact-checks/{report['id']}"
        f"/findings/{finding_id}",
        json={"status": "false_positive"},
    )
    assert response.status_code == 200, response.text
    updated = next(row for row in response.json()["findings"] if row["id"] == finding_id)
    assert updated["review_status"] == "false_positive"
    assert updated["quote"] == book["revisions"][0]["body"]


def test_stale_fact_check_finding_cannot_be_marked_false_positive(
    client, book_with_revisions, monkeypatch
):
    book = book_with_revisions
    configure_fake_model(monkeypatch, make_findings(book))
    queued = queue_fact_check(client, book)
    assert queued.status_code == 202
    assert run_fact_check(monkeypatch)["status"] == "completed"
    report = client.get(f"/v1/books/{book['book']['id']}/fact-checks/latest").json()
    finding_id = report["findings"][0]["id"]
    with SessionLocal() as db:
        claim = db.get(MemoryClaim, UUID(str(book["revisions"][0]["claim_id"])))
        claim.claim_text = "1993年在泉州入学。"
        db.commit()
    response = client.patch(
        f"/v1/books/{book['book']['id']}/fact-checks/{report['id']}"
        f"/findings/{finding_id}",
        json={"status": "false_positive"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BOOK_CHECK_NOT_REVIEWABLE"


def test_fact_check_is_tenant_scoped(client, book_with_revisions):
    book = book_with_revisions
    other_person = client.post(
        "/v1/persons", json={"display_name": "无权访问事实核查的人物"}
    ).json()
    other_book = client.post(
        "/v1/books",
        json={
            "source_mode": "legacy",
            "subject_id": other_person["id"],
            "title": "另一份书",
        },
    ).json()
    assert client.get(
        f"/v1/books/{other_book['id']}/fact-checks/{uuid4()}"
    ).status_code == 404
    assert client.get(
        f"/v1/books/{book['book']['id']}/fact-checks/{uuid4()}"
    ).status_code == 404

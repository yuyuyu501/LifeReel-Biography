from uuid import UUID, uuid4

import pytest
from lifereel_api.modules.book import importing
from lifereel_api.modules.book.models import Book, BookChapter, BookRevision
from lifereel_api.modules.identity.models import Person, Tenant
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.production.locking import execution_lock
from sqlalchemy import func, select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal

TEXT = (
    "人生书\n\n目录\n1. 童年\n2. 求学（未成稿）\n3. 工作\n\n"
    "童年\n\n第一段。\n\n第二段。\n\n工作\n\n工作经历。"
)
MARKDOWN = TEXT.replace("人生书\n", "# 人生书\n", 1).replace(
    "\n\n童年\n", "\n\n## 童年\n"
).replace("\n\n工作\n", "\n\n## 工作\n")


def person(client):
    return client.post("/v1/persons", json={"display_name": "导入合成人物"}).json()["id"]


def upload(client, subject_id, text=TEXT, filename="book.txt", **fields):
    return client.post(
        "/v1/books/import",
        data={"subject_id": subject_id, **fields},
        files={"file": (filename, text.encode() if isinstance(text, str) else text, "text/plain")},
    )


@pytest.mark.parametrize(("text", "filename", "format"), [
    (TEXT, "book.txt", "txt"),
    (MARKDOWN, "book.md", "md"),
    ("\ufeff" + MARKDOWN.replace("\n", "\r\n"), "book.markdown", "md"),
])
def test_import_edit_export_and_reimport(client, text, filename, format):
    subject_id = person(client)
    response = upload(client, subject_id, text, filename)
    assert response.status_code == 201, response.text
    book = response.json()
    assert book["title"] == "人生书"
    assert [row["title"] for row in book["chapters"]] == ["童年", "求学", "工作"]
    assert book["chapters"][1]["current"] is None
    assert book["chapters"][0]["current"]["body"] == "第一段。\n\n第二段。"
    assert all(not row["stale"] for row in book["chapters"])
    assert book["directory_version"] == 2
    chapter = book["chapters"][0]
    updated = client.patch(
        f"/v1/books/{book['id']}/chapters/{chapter['chapter_id']}",
        json={"expected_version": 1, "title": "童年", "body": "修改后的童年。\n\n保留段落。"},
    )
    assert updated.status_code == 200, updated.text
    revision = updated.json()["chapters"][0]["current"]
    assert revision["version_number"] == 2 and revision["author"] == "user"
    exported = client.get(f"/v1/books/{book['id']}/export?format={format}")
    assert exported.status_code == 200, exported.text
    restored = upload(client, person(client), exported.content, f"again.{format}")
    assert restored.status_code == 201, restored.text
    assert restored.json()["chapters"][0]["current"]["body"] == revision["body"]
    reopened = client.post("/v1/books", json={"subject_id": subject_id})
    assert len(reopened.json()["chapters"]) == 3
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 0


def test_override_title_and_markdown_revision_title(client):
    text = MARKDOWN.replace("## 工作", "## 工作回忆")
    result = upload(client, person(client), text, "BOOK.MD", title=" 新书名 ")
    assert result.status_code == 201, result.text
    assert result.json()["title"] == "新书名"
    assert result.json()["chapters"][2]["current"]["title"] == "工作回忆"


def test_legacy_txt_with_different_prose_titles(client):
    text = TEXT.replace("\n\n童年\n", "\n\n老屋里的家风\n").replace(
        "\n\n工作\n", "\n\n靠手艺，过日子\n",
    )
    response = upload(client, person(client), text)
    assert response.status_code == 201, response.text
    chapters = response.json()["chapters"]
    assert [chapter["title"] for chapter in chapters] == ["童年", "求学", "工作"]
    assert chapters[0]["current"]["title"] == "老屋里的家风"
    assert chapters[0]["current"]["body"] == "第一段。\n\n第二段。"
    assert chapters[2]["current"]["title"] == "靠手艺，过日子"
    assert chapters[2]["current"]["body"] == "工作经历。"


@pytest.mark.parametrize("format", ["txt", "md"])
def test_export_reimport_preserves_distinct_titles_and_heading_like_body(client, format):
    imported = upload(client, person(client)).json()
    chapter = imported["chapters"][2]
    body = "修家具的经历。\n\n工作\n\n这是正文中的同名段落。\n\n另一个短段落"
    response = client.patch(
        f"/v1/books/{imported['id']}/chapters/{chapter['chapter_id']}",
        json={"expected_version": 1, "title": "靠手艺，过日子", "body": body},
    )
    assert response.status_code == 200, response.text
    exported = client.get(f"/v1/books/{imported['id']}/export?format={format}")
    assert exported.status_code == 200, exported.text
    if format == "txt":
        assert "【第3章】靠手艺，过日子" in exported.text
    restored = upload(client, person(client), exported.content, f"again.{format}")
    assert restored.status_code == 201, restored.text
    current = restored.json()["chapters"][2]["current"]
    assert current["title"] == "靠手艺，过日子"
    assert current["body"] == body
    assert restored.json()["chapters"][1]["current"] is None


@pytest.mark.parametrize("text", [
    TEXT.replace("\n\n工作\n", "\n\n新工作标题\n") + "\n\n正文短段落\n\n内容。",
    TEXT.replace("\n\n工作\n", "\n\n【第2章】工作\n").replace(
        "\n\n童年\n", "\n\n【第1章】童年\n",
    ),
])
def test_ambiguous_legacy_or_invalid_numbered_chapters_are_rejected(client, text):
    response = upload(client, person(client), text)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "BOOK_IMPORT_FORMAT_INVALID"
    assert client.get("/v1/books").json() == []


def test_existing_book_conflicts_without_overwriting(client):
    subject_id = person(client)
    existing = client.post("/v1/books", json={"subject_id": subject_id}).json()
    response = upload(client, subject_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BOOK_ALREADY_EXISTS"
    assert client.get(f"/v1/books/{existing['id']}").json() == existing


def test_repeated_import_conflicts(client):
    subject_id = person(client)
    first = upload(client, subject_id)
    assert first.status_code == 201
    second = upload(client, subject_id)
    assert second.status_code == 409
    assert len(client.get("/v1/books").json()) == 1


@pytest.mark.parametrize(("text", "filename", "code"), [
    (b"", "book.txt", "BOOK_IMPORT_EMPTY"),
    (" \n\t", "book.txt", "BOOK_IMPORT_EMPTY"),
    (b"\xff\xfe", "book.txt", "BOOK_IMPORT_ENCODING_INVALID"),
    (TEXT, "book.pdf", "BOOK_IMPORT_FORMAT_INVALID"),
    (TEXT + "\x00", "book.txt", "BOOK_IMPORT_FORMAT_INVALID"),
    ("人生书\n\n没有目录", "book.txt", "BOOK_IMPORT_FORMAT_INVALID"),
    (TEXT.replace("3. 工作", "4. 工作"), "book.txt", "BOOK_IMPORT_FORMAT_INVALID"),
    (TEXT.replace("工作经历。", " "), "book.txt", "BOOK_IMPORT_FORMAT_INVALID"),
    (MARKDOWN + "\n\n## 多余章节\n\n内容", "book.md", "BOOK_IMPORT_FORMAT_INVALID"),
    (TEXT + "\n\n工作\n\n正文同名独立段落。", "book.txt", "BOOK_IMPORT_FORMAT_INVALID"),
    pytest.param(
        "x" * (importing.MAX_BYTES + 1), "book.txt", "BOOK_IMPORT_TOO_LARGE", id="too-large",
    ),
])
def test_invalid_upload_creates_no_book(client, text, filename, code):
    response = upload(client, person(client), text, filename)
    assert response.status_code == (413 if code == "BOOK_IMPORT_TOO_LARGE" else 422)
    assert response.json()["error"]["code"] == code
    assert client.get("/v1/books").json() == []


def test_person_ownership_and_missing_fields(client):
    with SessionLocal() as db:
        tenant = Tenant(name="Other import tenant", slug=uuid4().hex)
        db.add(tenant)
        db.flush()
        other = Person(tenant_id=tenant.id, display_name="Other person")
        db.add(other)
        db.commit()
        other_id = str(other.id)
    for subject_id in (other_id, str(uuid4())):
        response = upload(client, subject_id)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SUBJECT_NOT_FOUND"
    assert upload(client, "not-a-uuid").status_code == 422
    assert client.post("/v1/books/import", data={"subject_id": person(client)}).status_code == 422


def test_person_lock_prevents_parallel_create(client):
    subject_id = person(client)
    with SessionLocal() as db, execution_lock(db, UUID(subject_id)) as acquired:
        assert acquired
        assert upload(client, subject_id).json()["error"]["code"] == "BOOK_GENERATION_BUSY"


def test_revision_failure_rolls_back_entire_import(client, monkeypatch):
    subject_id = person(client)
    original = importing.writing.word_count
    calls = []

    def fail_second(body):
        calls.append(body)
        if len(calls) == 2:
            raise ValueError("Synthetic persistence failure")
        return original(body)

    monkeypatch.setattr(importing.writing, "word_count", fail_second)
    with SessionLocal() as db, pytest.raises(ValueError, match="Synthetic"):
        importing.import_book(
            db, get_settings().default_tenant_id, UUID(subject_id), None, TEXT.encode(), "book.txt"
        )
    with SessionLocal() as db:
        for model in (Book, BookChapter, BookRevision):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_read_only_role_cannot_import(client):
    from lifereel_api.modules.auth.dependencies import AuthContext, auth_context

    from lifereel_api.main import app

    subject_id = person(client)
    app.dependency_overrides[auth_context] = lambda: AuthContext(
        uuid4(), get_settings().default_tenant_id, "viewer"
    )
    try:
        response = upload(client, subject_id)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AUTH_READ_ONLY"
    finally:
        app.dependency_overrides.pop(auth_context)
    assert client.get("/v1/books").json() == []


def test_imported_book_cannot_be_read_or_exported_by_other_tenant(client):
    subject_id = person(client)
    imported = upload(client, subject_id).json()
    with SessionLocal() as db:
        other = Tenant(name="Hidden book tenant", slug=uuid4().hex)
        db.add(other)
        db.commit()
        other_id = str(other.id)
    for suffix in ("", "/export", f"/chapters/{imported['chapters'][0]['chapter_id']}/versions"):
        response = client.get(
            f"/v1/books/{imported['id']}{suffix}", headers={"X-Tenant-ID": other_id}
        )
        assert response.status_code == 404


@pytest.mark.parametrize("title", [" ", "x" * 181, "Title\nbad"])
def test_invalid_title_creates_no_book(client, title):
    assert upload(client, person(client), title=title).status_code == 422
    assert client.get("/v1/books").json() == []


def test_chapter_and_title_limits():
    from lifereel_api.core.errors import ApiError

    for text in (
        TEXT.replace("人生书", "x" * 181, 1),
        TEXT.replace("1. 童年", "1. " + "x" * 181),
        "书名\n\n目录\n" + "\n".join(f"{i}. 章{i}（未成稿）" for i in range(1, 42)),
    ):
        with pytest.raises(ApiError) as exc:
            importing.parse(text.encode(), "book.txt")
        assert exc.value.code == "BOOK_IMPORT_FORMAT_INVALID"

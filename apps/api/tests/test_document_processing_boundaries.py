import hashlib
from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError
from lifereel_api.core.processing_limits import ProcessingLimits
from lifereel_api.modules.evidence import documents
from lifereel_api.modules.evidence.models import EvidenceObservation, SourceAsset
from lifereel_api.modules.evidence.storage import LocalPrivateStorage
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


@pytest.fixture(autouse=True)
def isolated_documents(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "local_storage_path", str(tmp_path / "storage"))
    monkeypatch.setattr(
        OpenAICompatibleClient, "chat_json",
        lambda *args, **kwargs: pytest.fail("document boundaries must not call a model"),
    )


def test_valid_50_mib_document_is_preserved_but_processing_explicitly_rejected(client, tmp_path,
                                                                           monkeypatch):
    source = tmp_path / "large.md"
    block = b"A valid family memory.\n".ljust(1024 * 1024, b"a")
    with source.open("wb") as output:
        for _ in range(50):
            output.write(block)
    with source.open("rb") as content:
        original_hash = hashlib.file_digest(content, "sha256").hexdigest()
    person = client.post("/v1/persons", json={"display_name": "Document budget"}).json()
    with source.open("rb") as content:
        uploaded = client.post(
            "/v1/evidence/assets", data={"subject_id": person["id"], "kind": "document"},
            files={"file": ("large.md", content, "text/markdown")},
        )
    assert uploaded.status_code == 201
    asset = uploaded.json()
    assert asset["byte_size"] == 50 * 1024 * 1024
    monkeypatch.setattr(LocalPrivateStorage, "get", lambda *args: pytest.fail("full blob read"))
    response = client.post(f"/v1/evidence/assets/{asset['id']}/analyze")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "EVIDENCE_TEXT_TOO_LARGE"
    context = response.json()["error"]["context"]
    assert context["reason"] == "processing_budget_exceeded"
    assert context["stage"] == "document_extract"
    assert context["coverage"] == "none"
    assert context["source_asset_id"] == asset["id"]
    assert context["original_preserved"] is True
    with SessionLocal() as db:
        saved = db.scalar(select(SourceAsset))
        assert saved.analysis_status != "analyzed"
        assert db.scalar(select(EvidenceObservation)) is None
    downloaded = client.get(f"/v1/evidence/assets/{asset['id']}/content")
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == original_hash
    compiled = client.post("/v1/memories/compile", json={"subject_id": person["id"]})
    assert compiled.status_code == 200
    assert compiled.json()["created_count"] == 0


@pytest.mark.parametrize("mime_type", ["text/plain", "text/markdown"])
def test_complete_document_at_character_budget_keeps_tail_and_provenance(client, monkeypatch,
                                                                       mime_type):
    text = "家庭记录" * 2048 + "末尾不能丢"
    monkeypatch.setattr(documents, "get_processing_limits", lambda: ProcessingLimits(
        document_extract_max_chars=len(text),
    ))
    person = client.post("/v1/persons", json={"display_name": "Complete document"}).json()
    content = b"\xef\xbb\xbf" + text.encode()
    asset = client.post(
        "/v1/evidence/assets", data={"subject_id": person["id"], "kind": "document"},
        files={"file": ("memory.txt", BytesIO(content), mime_type)},
    ).json()
    response = client.post(f"/v1/evidence/assets/{asset['id']}/analyze")
    assert response.status_code == 200
    observation = response.json()
    assert observation["text"] == text
    assert observation["locator"]["coverage"] == "full"
    assert observation["locator"]["source_sha256"] == hashlib.sha256(content).hexdigest()
    assert observation["locator"]["extracted_chars"] == len(text)


def _pdf(pages):
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 10 200 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = stream
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_budget_counts_all_pages_and_never_returns_a_partial_document(monkeypatch):
    content = _pdf(["First page", "Last page"])
    complete = documents.extract_document(content, "application/pdf", "source-id")
    assert "First page" in complete and "Last page" in complete
    monkeypatch.setattr(documents, "get_processing_limits", lambda: ProcessingLimits(
        document_extract_max_chars=10,
    ))
    with pytest.raises(ApiError) as exc:
        documents.extract_document(content, "application/pdf", "source-id")
    assert exc.value.status_code == 413
    assert exc.value.context["coverage"] == "none"
    monkeypatch.setattr(documents, "get_processing_limits", lambda: ProcessingLimits(
        document_extract_max_pages=1,
    ))
    with pytest.raises(ApiError) as exc:
        documents.extract_document(content, "application/pdf", "source-id")
    assert exc.value.context["limit_pages"] == 1


def test_whitespace_is_budgeted_and_invalid_utf8_is_not_silently_replaced(monkeypatch):
    monkeypatch.setattr(documents, "get_processing_limits", lambda: ProcessingLimits(
        document_extract_max_chars=4,
    ))
    with pytest.raises(ApiError):
        documents.extract_document(b"     ", "text/plain", "source-id")
    with pytest.raises(UnicodeDecodeError):
        documents.extract_document(b"abc\xff", "text/plain", "source-id")

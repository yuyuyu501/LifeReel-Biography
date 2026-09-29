from __future__ import annotations

import codecs
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from pypdf import PdfReader

from lifereel_api.core.errors import ErrorCode
from lifereel_api.core.processing_limits import get_processing_limits, require_budget


def extract_document(source: bytes | Path, mime_type: str, source_asset_id: str) -> str:
    """Return the complete extracted text, or reject without persisting a partial result."""
    with (source.open("rb") if isinstance(source, Path) else BytesIO(source)) as stream:
        return _extract(stream, mime_type, source_asset_id)


def _extract(stream: BinaryIO, mime_type: str, source_asset_id: str) -> str:
    limits = get_processing_limits()
    parts: list[str] = []
    consumed = 0

    def append(text: str) -> None:
        nonlocal consumed
        consumed += len(text)
        require_budget(
            consumed, limits.document_extract_max_chars, stage="document_extract",
            code=ErrorCode.EVIDENCE_TEXT_TOO_LARGE, source_asset_id=source_asset_id,
        )
        parts.append(text)

    if mime_type == "application/pdf":
        reader = PdfReader(stream)
        require_budget(
            len(reader.pages), limits.document_extract_max_pages, stage="document_extract",
            code=ErrorCode.EVIDENCE_TEXT_TOO_LARGE, unit="pages", source_asset_id=source_asset_id,
        )
        for index, page in enumerate(reader.pages):
            if index:
                append("\n\n")
            append(page.extract_text() or "")
    else:
        decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
        while chunk := stream.read(4096):
            append(decoder.decode(chunk, final=False))
        append(decoder.decode(b"", final=True))
    # Whitespace counts against the budget too: stripping before counting would
    # permit arbitrarily large whitespace-only inputs to evade extraction limits.
    return "".join(parts).strip()

"""Person-scoped retrieval of current records and versioned original answers."""

import json
import re
from copy import deepcopy

from sqlalchemy import select

from lifereel_api.modules.interview.models import InterviewRound, InterviewSession

VERSION = "interview-retrieval-20261014-v1"
MAX_HISTORY = 1000
MAX_SOURCES = 8
MAX_CHARS = 14000
WINDOW = 2200


def terms(text):
    words = set(re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text.lower()))
    return words | {word[i : i + 2] for word in words for i in range(len(word) - 1)}


def relevance(query, text):
    shared = terms(query) & terms(text)
    return sum(5 if word.isdigit() else len(word) for word in shared)


def select_sources(rows, query, *, excluded=()):
    """Keep exact windows, including adjacent answers needed for antecedents."""
    ranked = sorted(
        (
            (relevance(query, row["answer"]), i)
            for i, row in enumerate(rows)
            if row["id"] not in excluded
        ),
        reverse=True,
    )
    indices = []
    for score, index in ranked:
        if not score:
            continue
        for candidate in (index, index - 1, index + 1):
            if (
                0 <= candidate < len(rows)
                and candidate not in indices
                and rows[candidate]["id"] not in excluded
            ):
                indices.append(candidate)
            if len(indices) == MAX_SOURCES:
                break
        if len(indices) == MAX_SOURCES:
            break
    selected, remaining = [], MAX_CHARS
    for index in sorted(indices):
        row = rows[index]
        text = row["answer"]
        start = 0
        if len(text) > WINDOW:
            hits = [text.find(word) for word in terms(query) if word in text]
            start = max(0, min(hits, default=0) - WINDOW // 3)
        quote = text[start : start + min(WINDOW, remaining)]
        if not quote:
            break
        selected.append(
            {
                "source_id": row["id"],
                "type": "interview_round",
                "id": row["record_id"],
                "version": row["version"],
                "quote": quote,
                "start": start,
                "end": start + len(quote),
            }
        )
        remaining -= len(quote)
    return selected


def enrich(db, tenant, profile_id, material, entries):
    statement = (
        select(InterviewRound)
        .join(InterviewSession)
        .where(
            InterviewSession.tenant_id == tenant,
            InterviewSession.profile_id == profile_id,
            InterviewRound.tenant_id == tenant,
            InterviewRound.answer_text.is_not(None),
        )
        .order_by(InterviewRound.created_at.desc(), InterviewRound.id.desc())
        .limit(MAX_HISTORY + 1)
    )
    records = list(db.scalars(statement))
    truncated = len(records) > MAX_HISTORY
    rows = [
        {
            "id": f"round:{r.id}:v{r.answer_version}",
            "record_id": str(r.id),
            "version": r.answer_version,
            "answer": r.answer_text,
        }
        for r in reversed(records[:MAX_HISTORY])
        if str(r.id) != material["current_source"].get("id")
    ]
    return enrich_material(material, entries, rows, truncated=truncated)


def enrich_material(material, entries, rows, *, truncated=False):
    """Pure selection also used by the frozen local experiment."""
    result = deepcopy(material)
    query = material["new_answer"] + " " + " ".join(material.get("recent_questions", [])[:2])
    selected = select_sources(rows, query, excluded=[r["id"] for r in material["recent_dialogue"]])
    ranked = sorted(
        entries,
        key=lambda e: relevance(query, json.dumps(e["value"], ensure_ascii=False)),
        reverse=True,
    )
    present = {e["id"] for e in result["current_entries"]}
    selected_ids = {s["id"] for s in selected}
    for entry in ranked:
        source = entry.get("source", {})
        linked = any(
            str(e.get("id")) in selected_ids for e in [source, *source.get("evidence", [])]
        )
        score = relevance(query, json.dumps(entry["value"], ensure_ascii=False))
        if entry["id"] in present or not (linked or score):
            continue
        copied = deepcopy(entry)
        copied["source_id"] = f"entry:{entry['id']}:v{entry['version_number']}"
        if len(json.dumps(copied, ensure_ascii=False)) > 6000:
            continue
        tentative = [*result["current_entries"], copied]
        if len(tentative) > 80 or len(json.dumps(tentative, ensure_ascii=False)) > 42000:
            break
        result["current_entries"] = tentative
        present.add(entry["id"])
    result["retrieved_sources"] = selected
    result["source_ids"] = list(
        dict.fromkeys(
            [
                *material["source_ids"],
                *[s["source_id"] for s in selected],
                *[e["source_id"] for e in result["current_entries"]],
            ]
        )
    )
    result["retrieval"] = {
        "version": VERSION,
        "method": "structured_and_lexical",
        "history_scanned": len(rows),
        "history_truncated": truncated,
        "source_ids": [s["source_id"] for s in selected],
        "entry_ids": [
            e["id"]
            for e in result["current_entries"]
            if e["id"] not in {r["id"] for r in material["current_entries"]}
        ],
        "retrieved_chars": sum(len(s["quote"]) for s in selected),
    }
    return result

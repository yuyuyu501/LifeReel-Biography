"""Offline checks for bounded normalization, provenance gates and Sol recovery."""

import json
from copy import deepcopy

import pytest
from interview_entity_v2 import (
    ALL_CASES,
    Draft,
    apply_v2,
    attach_spans,
    entity_input,
    gate_reason_v2,
    normalize_protocol,
    provider_call,
    run_case,
    same_pending,
    strict_schema,
)
from pydantic import ValidationError


def candidate(**changes):
    return {
        "candidate_id": "F1",
        "entity_id": "father",
        "entity_candidates": ["father"],
        "resolution": "contextual",
        "predicate": "birth_year",
        "value": "1938",
        "status": "reported",
        "object_entity_id": None,
        "evidence": [{"source_id": "U2", "quote": "1938年出生的是他，不是我。"}],
        "binding_evidence": [
            {"source_id": "U2", "quote": "父亲现在还活着，1938年出生的是他，不是我。"}
        ],
        **changes,
    }


SOURCES = [
    {"id": "U1", "text": "之前说过搬家。"},
    {"id": "U2", "text": "父亲现在还活着，1938年出生的是他，不是我。"},
]


def test_same_message_reference_merges_actor_provenance_and_preserves_raw():
    raw = {"candidates": [candidate()], "pending": []}
    original = deepcopy(raw)
    output, rejected, _ = apply_v2(raw, SOURCES)
    assert not rejected
    assert output["facts"][0]["fields"] == ["family.members[]"]
    assert len(output["facts"][0]["evidence"]) == 2
    for e in output["facts"][0]["evidence"]:
        assert SOURCES[1]["text"][e["start"] : e["end"]] == e["quote"]
    assert raw == original


def test_same_message_without_actor_anchor_is_rejected():
    row = candidate(binding_evidence=[{"source_id": "U2", "quote": "1938年出生的是他，不是我。"}])
    assert gate_reason_v2(row, SOURCES) == "missing_entity_anchor"


def test_english_object_id_maps_to_display_name_only_when_id_matches():
    sources = [{"id": "U1", "text": "父亲住叔叔家。"}]
    row = candidate(
        resolution="explicit",
        predicate="host",
        value="uncle",
        object_entity_id="uncle",
        evidence=[{"source_id": "U1", "quote": "父亲住叔叔家。"}],
        binding_evidence=[{"source_id": "U1", "quote": "父亲住叔叔家。"}],
    )
    output, rejected, _ = apply_v2({"candidates": [row], "pending": []}, sources)
    assert not rejected and output["facts"][0]["value"] == "叔叔"
    assert gate_reason_v2({**row, "object_entity_id": "sister"}, sources) == "unresolved_object"


def test_repairs_only_allowlisted_syntax_without_changing_facts():
    row = candidate()
    row["candidate"] = row.pop("candidate_id")
    row["note"] = "annotation"
    raw = {"candidates": [row]}
    original = deepcopy(raw)
    fixed, changes = normalize_protocol(raw)
    assert fixed["pending"] == [] and len(changes) == 3
    assert fixed["candidates"][0] == candidate()
    assert raw == original


@pytest.mark.parametrize(
    "changes",
    [
        {"value": 1938},
        {"status": "confirmed"},
        {"fields": ["identity.birth_time"]},
        {"entity_id": "invented"},
    ],
)
def test_semantic_or_unknown_fields_are_not_repaired(changes):
    row = candidate(**changes)
    if changes == {"entity_id": "invented"}:
        assert gate_reason_v2(row, SOURCES) in {"unresolved_entity", "unknown_entity"}
    else:
        with pytest.raises(ValidationError):
            normalize_protocol({"candidates": [row], "pending": []})


def test_true_ambiguity_cannot_be_silently_normalized():
    row = candidate(entity_candidates=["father", "uncle"])
    output, rejected, _ = apply_v2({"candidates": [row]}, SOURCES)
    assert not output["facts"] and rejected[0]["reason"] == "unresolved_entity"


def test_bad_punctuation_or_stitched_quote_is_never_corrected():
    bad = [{"source_id": "U2", "quote": "父亲现在还活着……不是我。"}]
    assert gate_reason_v2(candidate(evidence=bad), SOURCES) == "invalid_quote"
    with pytest.raises(ValueError, match="invalid_quote"):
        attach_spans(bad, SOURCES)


def test_pending_dedup_requires_related_evidence_and_same_people():
    a = {
        "entity_candidates": ["father", "uncle"],
        "evidence": [{"source_id": "U2", "quote": "他去了南京"}],
    }
    b = {**a, "evidence": [{"source_id": "U2", "quote": "他去了南京，后来住下"}]}
    assert same_pending(a, b)
    assert not same_pending(a, {**b, "evidence": [{"source_id": "U2", "quote": "他生于1944年"}]})


def test_gold_and_profile_fields_are_never_passed_to_provider():
    assert not {"gold", "fields", "category", "must_abstain"} & entity_input(ALL_CASES[0]).keys()


def test_strict_schema_requires_all_properties_and_forbids_unknown_keys():
    schema = strict_schema()
    for obj in [schema, *schema["$defs"].values()]:
        if obj.get("type") == "object":
            assert obj["additionalProperties"] is False
            assert set(obj["required"]) == set(obj["properties"])
    assert Draft.model_validate({"candidates": [], "pending": [], "review_log": []})


def test_provider_cache_never_retries_uncertain_failed_calls(tmp_path, monkeypatch):
    (tmp_path / "direct-receipt.json").write_text(
        json.dumps({"status": "failed", "error": "RemoteProtocolError"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        "interview_entity_v2.httpx.post", lambda *a, **k: pytest.fail("must not retry")
    )
    with pytest.raises(RuntimeError, match="RemoteProtocolError"):
        provider_call(("https://example.invalid", "unused"), "unused", "direct", "", {}, tmp_path)


def test_sol_can_recover_from_unrepairable_lite_protocol_failure(tmp_path, monkeypatch):
    seen = []

    def fake_call(credentials, model, stage, system, data, directory, schema=None):
        seen.append((stage, data))
        if stage == "roles":
            return {"roles": [], "rewritten": "", "unresolved": []}
        if stage in {"direct", "role_extract"}:
            return {"candidates": [{"wrong": "protocol"}], "pending": []}
        return {"candidates": [], "pending": [], "review_log": []}

    monkeypatch.setattr("interview_entity_v2.provider_call", fake_call)
    formats = {name: {"format": "json_object"} for name in ("lite", "sol")}
    results = run_case(
        ALL_CASES[0], 1, {"lite": (None, None), "sol": (None, None)}, formats, tmp_path
    )
    assert [r["status"] for r in results] == ["failed", "failed", "ok", "ok"]
    reviews = [data for stage, data in seen if stage.endswith("review")]
    assert len(reviews) == 2 and all(r["upstream_error"] for r in reviews)
    assert all(r["sources"] == ALL_CASES[0]["sources"] and "gold" not in r for r in reviews)

"""Test entity experiment controls without paid provider calls."""

import json
from copy import deepcopy

import pytest
from interview_entity_methods import (
    ALL_CASES,
    ENTITIES,
    FIELD_MAP,
    PREDICATES,
    apply_draft,
    entity_input,
    gate_reason,
    map_field,
    provider_call,
)
from pydantic import ValidationError


def candidate(**overrides):
    return {
        "candidate_id": "F1",
        "entity_id": "mother",
        "entity_candidates": ["mother"],
        "resolution": "explicit",
        "predicate": "birth_year",
        "value": "1941",
        "status": "reported",
        "object_entity_id": None,
        "evidence": [{"source_id": "U1", "quote": "妈妈1941年出生"}],
        "binding_evidence": [{"source_id": "U1", "quote": "妈妈1941年出生"}],
        **overrides,
    }


SOURCES = [{"id": "U1", "text": "妈妈1941年出生"}]


def test_extraction_input_has_no_gold_case_labels_or_profile_fields():
    payload = entity_input(ALL_CASES[0])
    assert not {"gold", "fields", "category", "must_abstain", "requires_pending"} & payload.keys()
    assert payload["entities"][0]["id"] == "self"


def test_parent_identity_can_never_be_mapped_to_self_birth_field():
    output, rejected = apply_draft(
        {"candidates": [candidate()], "pending": []}, SOURCES, gated=True
    )
    assert not rejected
    assert output["facts"][0]["subject"] == "母亲"
    assert output["facts"][0]["fields"] == ["family.members[]"]
    row = candidate(entity_id="self", entity_candidates=["self"])
    assert map_field(row) == "identity.birth_time"


def test_ambiguous_person_cannot_be_saved_even_if_model_selects_one():
    row = candidate(entity_candidates=["mother", "aunt"])
    raw = {"candidates": [row], "pending": []}
    before = deepcopy(raw)
    plain, _ = apply_draft(raw, SOURCES, gated=False)
    checked, rejected = apply_draft(raw, SOURCES, gated=True)
    assert len(plain["facts"]) == 1 and checked["facts"] == []
    assert rejected[0]["reason"] == "unresolved_entity"
    assert checked["abstentions"][0]["candidate_id"] == "F1"
    assert raw == before


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"entity_id": "invented", "entity_candidates": ["invented"]}, "unknown_entity"),
        ({"evidence": [{"source_id": "U1", "quote": "妈妈1940年出生"}]}, "invalid_quote"),
        ({"binding_evidence": []}, "missing_binding_quote"),
    ],
)
def test_provenance_and_identity_gates(change, reason):
    assert gate_reason(candidate(**change), SOURCES) == reason


def test_old_quote_without_current_confirmation_is_rejected():
    sources = [*SOURCES, {"id": "U2", "text": "今天聊工作"}]
    assert gate_reason(candidate(), sources) == "missing_current_source"


def test_phone_object_and_value_must_agree_and_organisation_needs_original_name():
    row = candidate(predicate="call_recipient", object_entity_id="father", value="儿子")
    assert gate_reason(row, SOURCES) == "unresolved_object"
    row = candidate(
        entity_id="org:不存在的厂",
        entity_candidates=["org:不存在的厂"],
        predicate="closure_year",
        value="2002",
    )
    assert gate_reason(row, SOURCES) == "unknown_entity"


def test_every_predicate_maps_to_existing_field_for_every_person():
    for predicate in PREDICATES:
        for entity in ENTITIES:
            assert map_field(candidate(entity_id=entity, predicate=predicate)) in FIELD_MAP


def test_same_turn_pending_does_not_remove_unrelated_confirmed_fact():
    raw = {
        "candidates": [candidate()],
        "pending": [
            {
                "entity_candidates": ["mother", "aunt"],
                "reason": "另一件事还不确定",
                "question": "另一件事说的是谁？",
                "evidence": [{"source_id": "U1", "quote": "妈妈1941年出生"}],
            }
        ],
    }
    output, _ = apply_draft(raw, SOURCES, gated=True)
    assert len(output["facts"]) == len(output["abstentions"]) == 1


def test_no_model_selected_fields_or_duplicate_candidate_ids_are_accepted():
    row = candidate(fields=["identity.birth_time"])
    with pytest.raises(ValidationError):
        apply_draft({"candidates": [row], "pending": []}, SOURCES, gated=True)
    with pytest.raises(ValueError, match="candidate_ids"):
        apply_draft({"candidates": [candidate(), candidate()], "pending": []}, SOURCES, gated=True)


def test_failed_cached_provider_request_is_not_retried(tmp_path, monkeypatch):
    (tmp_path / "direct-receipt.json").write_text(
        json.dumps({"status": "failed", "error": "http_503"}),
        encoding="utf-8",
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("provider must not be called")

    monkeypatch.setattr("interview_entity_methods.httpx.post", forbidden)
    with pytest.raises(RuntimeError, match="http_503"):
        provider_call(("https://example.invalid", "unused"), "unused", "direct", "", {}, tmp_path)

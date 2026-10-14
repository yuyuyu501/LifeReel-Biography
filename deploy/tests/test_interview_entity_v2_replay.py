"""The session metadata exception must not relax identity or quote validation."""

from copy import deepcopy

import pytest
from interview_entity_v2_replay import recover_metadata
from test_interview_entity_v2 import candidate


def result(row, reason="missing_entity_anchor"):
    return {
        "status": "ok",
        "output": {"facts": [], "abstentions": [{"candidate_id": "F1"}]},
        "rejected": [{"candidate": row, "reason": reason}],
    }


def test_unstated_first_person_material_status_uses_session_scope():
    quote = [{"source_id": "U1", "quote": "1992年纸质结婚照没上传，下次再给你。"}]
    row = candidate(
        entity_id="self",
        entity_candidates=["self"],
        predicate="material_status",
        value="1992年纸质结婚照未上传",
        evidence=quote,
        binding_evidence=quote,
    )
    source = [{"id": "U1", "text": quote[0]["quote"]}]
    original = result(row)
    before = deepcopy(original)
    repaired = recover_metadata(original, source)
    assert len(repaired["output"]["facts"]) == 1
    assert not repaired["output"]["abstentions"] and not repaired["rejected"]
    assert repaired["posthoc_changes"] and original == before


@pytest.mark.parametrize(
    "predicate", ["birth_year", "alive", "moved_to", "host", "debt_year", "debt_cause"]
)
def test_identity_and_events_cannot_use_metadata_exception(predicate):
    row = candidate(entity_id="self", entity_candidates=["self"], predicate=predicate)
    repaired = recover_metadata(result(row), [{"id": "U2", "text": "1938年出生的是他。"}])
    assert not repaired["output"]["facts"] and repaired["rejected"]


def test_false_quote_still_rejected_even_for_metadata():
    row = candidate(
        entity_id="self",
        entity_candidates=["self"],
        predicate="material_status",
        evidence=[{"source_id": "U1", "quote": "已上传"}],
        binding_evidence=[{"source_id": "U1", "quote": "已上传"}],
    )
    repaired = recover_metadata(result(row), [{"id": "U1", "text": "没上传"}])
    assert not repaired["output"]["facts"] and repaired["rejected"]


def test_ambiguous_actor_and_real_family_member_remain_rejected():
    for entity, candidates in (("self", ["self", "father"]), ("father", ["father"])):
        row = candidate(entity_id=entity, entity_candidates=candidates, predicate="deferred_topic")
        repaired = recover_metadata(result(row), [])
        assert not repaired["output"]["facts"] and repaired["rejected"]

"""Fixed synthetic organization contracts; v01-v08 are validation IDs, not a blind holdout."""

from copy import deepcopy
from importlib import import_module
from uuid import uuid4

import pytest
from lifereel_api.modules.interview import d4
from test_interview_d4 import draft, fact, material


def stored(change, quote, *, source_id="original"):
    return {
        **deepcopy(change), "id": str(uuid4()), "version_number": 1,
        "source": {"type": "test", "id": source_id, "version": 1, "quote": quote},
    }


def adapt(rows, data):
    trace = {}
    result = d4.adapt(d4.Draft.model_validate(draft(rows)), data, trace)
    return result, trace


@pytest.mark.parametrize("predicate,value,text", [
    ("workplace", "图书馆", "我在图书馆工作。"),
    ("workplace", "印刷厂", "我在印刷厂工作。"),
    ("employment_start", "1998年", "我1998年入职。"),
    ("employment_end", "2005年", "我2005年离职。"),
], ids=["d01", "d02", "v01", "v02"])
def test_reused_original_evidence_links_one_existing_event(predicate, value, text):
    original, _ = adapt(
        [fact(predicate=predicate, value=value, quote=text, event_key="first")], material(text)
    )
    entry = stored(original["changes"][0], text, source_id="test")
    entry["source_id"] = "entry:original:v1"
    answer = "对，我说的就是那一段。"
    row = fact(
        predicate=predicate, value=value, quote=answer, event_key="different-model-key",
        evidence=[{"source_id": "entry:original:v1", "quote": text},
                  {"source_id": "current:test:v1", "quote": answer}],
    )
    data = {**material(answer), "current_entries": [entry]}
    output, _ = adapt([row], data)
    assert output["changes"][0].get("id") == entry["id"]
    assert len(output["changes"][0]["value"]["facts"]) == 1


@pytest.mark.parametrize("predicate,old,new", [
    ("work_responsibilities", "整理档案", "带徒弟"),
    ("work_events", "参加检修", "负责验收"),
    ("relationships_shared_life", "住在老家", "住在城里"),
    ("present_interests", "看书", "散步"),
], ids=["d03", "d04", "v03", "v04"])
def test_correction_only_replaces_same_event(predicate, old, new):
    previous = [
        {"subject": "本人", "entity_id": "self", "predicate": predicate,
         "value": value, "status": "reported", "event_key": key}
        for value, key in ((old, "target"), ("另一阶段的经历", "other"))
    ]
    row = d4.Candidate.model_validate(fact(
        predicate=predicate, value=new, event_key="target", quote="更正一下。"
    ))
    result, _ = d4.merge_atoms(previous, [row], [], correction=True, reconciliations={})
    assert {a["value"] for a in result} == {new, "另一阶段的经历"}
    assert previous[0]["value"] == old


@pytest.mark.parametrize("state,certainty,expected", [
    ("filled", "reported", "recorded"),
    ("unknown", "reported", "unknown"),
    ("declined", "reported", "declined"),
    ("filled", "disputed", "needs_clarification"),
], ids=["d05", "d06", "v05", "v06"])
def test_coverage_describes_effective_state_without_claiming_sufficiency(
    state, certainty, expected,
):
    organization = import_module("lifereel_api.modules.interview.organization")
    entry = stored({"field_key": "work.meaning", "record_key": "single", "value": "按原话整理",
                    "state": state, "certainty": certainty, "use_scope": "internal"}, "原始回答")
    summary = organization.context([entry], [entry])
    field = next(f for f in summary["coverage"] if f["field_key"] == "work.meaning")
    assert field["states"] == [expected]
    assert field["entry_ids"] == [entry["id"]]
    assert "sufficient" not in field and "confirmed" not in field
    assert entry["use_scope"] == "internal"


@pytest.mark.parametrize("entity,predicate,value,text", [
    ("father", "moved_to", "长沙", "父亲去了长沙。"),
    ("self", "work_responsibilities", "带徒弟", "我负责带徒弟。"),
    ("self", "learning_records", "上过学校但没毕业", "我上过学校但没毕业。"),
    ("self", "work_events", "可能是1998年参加检修", "我可能是1998年参加检修。"),
], ids=["d07", "d08", "d09", "v07"])
def test_each_atom_retains_its_own_verified_original_evidence(entity, predicate, value, text):
    output, _ = adapt([fact(entity=entity, predicate=predicate, value=value, quote=text)],
                      material(text))
    atom = output["changes"][0]["value"]["facts"][0]
    assert atom["entity_id"] == entity and atom["value"] == value
    assert atom["evidence"][0]["quote"] == text
    assert atom["evidence"][0]["id"] == "test"
    assert atom["evidence"][0]["start"] == 0
    assert atom["evidence"][0]["end"] == len(text)


@pytest.mark.parametrize("variant", ["different_source", "ambiguous", "different_person",
                                     "unknown_entry"], ids=["d10", "d11", "d12", "v08"])
def test_similarity_alone_does_not_link_events(variant):
    text = "我在图书馆工作。"
    initial, _ = adapt([fact(predicate="workplace", value="图书馆", quote=text,
                             event_key="old")], material(text))
    entry = stored(initial["changes"][0], text)
    data = {**material(text), "current_entries": [entry]}
    if variant == "different_source":
        entry["value"]["facts"][0]["evidence"][0]["id"] = "another-source"
    elif variant == "ambiguous":
        data["current_entries"].append({**deepcopy(entry), "id": str(uuid4()),
                                        "record_key": "another"})
    elif variant == "different_person":
        entry["value"]["facts"][0]["entity_id"] = "father"
    elif variant == "unknown_entry":
        entry["certainty"] = "disputed"
    output, _ = adapt([fact(predicate="workplace", value="图书馆", quote=text,
                            event_key="new")], data)
    assert output["changes"][0].get("id") is None
    assert data["current_entries"][0] == entry


@pytest.mark.parametrize("predicate,value,quote", [
    ("birth_year", "1970年", "我1970年出生"),
    ("moved_to", "长沙", "父亲去了长沙"),
    ("work_responsibilities", "带徒弟", "我负责带徒弟"),
    ("work_events", "没有参加验收", "我没有参加验收"),
], ids=["d13", "d14", "d15", "d16"])
def test_unsupported_fact_is_never_saved(predicate, value, quote):
    data = material("我今天想聊工作。")
    output, trace = adapt([fact(predicate=predicate, value=value, quote=quote)], data)
    assert output["changes"] == []
    assert trace["rejected_candidates"]

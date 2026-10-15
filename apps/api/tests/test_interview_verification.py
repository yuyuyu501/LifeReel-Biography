"""Regression checks for recording verification, including persisted profile values."""

import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from lifereel_api.modules.interview import d4, grounding
from lifereel_api.modules.interview.profile_extraction import process
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient
from test_interview_d4 import draft, enabled, fact, material  # noqa: F401
from test_interview_grounding_retrieval import reviewed

from lifereel_api.core.database import SessionLocal


def prior(predicate="workplace", value="照相馆", field="work.records[]", entity="self"):
    return {
        "id": str(uuid4()), "field_key": field, "record_key": "old-event",
        "state": "filled", "certainty": "reported", "use_scope": "works",
        "value": {"facts": [{"subject": d4.label(entity), "entity_id": entity,
                             "predicate": predicate, "value": value, "status": "reported"}]},
        "source_id": "entry:old:v1",
        "source": {"type": "test", "id": "old", "version": 1,
                   "quote": "我1987年进照相馆，郭师傅教我装订。"},
    }


def supported(data, row, old=None, relation="new", index=None):
    raw = reviewed([row])
    raw["coverage"] = [{"quote": data["new_answer"], "disposition": "facts",
                        "candidate_ids": [row["candidate_id"]]}]
    raw["question_support"]["evidence"] = deepcopy(row["evidence"])
    check = raw["support_checks"][0]
    check.update(relation=relation, prior_fact_index=index)
    if old:
        check["components"][0]["evidence"].append(
            {"source_id": old["source_id"], "quote": old["source"]["quote"]}
        )
    return raw


@pytest.mark.parametrize("entity", ["self", "person:郭师傅", "org:织布厂"])
def test_generic_action_cannot_silently_route_to_work_or_family(entity):
    data = material("我保存了照片。郭师傅教我装订。织布厂停产了。")
    row = fact(entity=entity, predicate="event_action", value="行动", quote=data["new_answer"])
    trace = {}
    result = d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)
    assert not result["changes"]
    assert trace["rejected_candidates"][0]["reason"] == "ambiguous_action_domain"


def test_named_person_requires_actual_family_relation():
    data = material("郭师傅教我装订。")
    row = fact(entity="person:郭师傅", predicate="family_members", value="教我装订",
               quote=data["new_answer"])
    trace = {}
    assert not d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)["changes"]
    assert trace["rejected_candidates"][0]["reason"] == "unverified_family_relation"
    row["predicate"] = "learning_teachers"
    assert d4.adapt(d4.Draft.model_validate(draft([row])), data, {})["changes"][0][
        "field_key"
    ] == "learning.teachers[]"


def test_generic_workplace_refinement_and_real_conflict_are_distinct():
    old = prior()
    data = material("我工作的那家就叫江城照相馆。")
    data["current_entries"] = [old]
    row = fact(predicate="workplace", value="江城照相馆", quote=data["new_answer"],
               entry_id=old["id"])
    trace = {}
    result = d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)
    assert not trace["conflict_indices"]
    assert [a["value"] for a in result["changes"][0]["value"]["facts"]] == ["江城照相馆"]
    old["value"]["facts"][0]["value"] = "南城照相馆"
    d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)
    assert trace["conflict_indices"] == [0]


def test_indefinite_unit_name_is_refinement_but_negation_is_not():
    old = {"predicate": "workplace", "value": "一家印刷厂", "status": "reported"}
    new = {"predicate": "workplace", "value": "衡阳长风印刷厂", "status": "reported"}
    assert d4.workplace_refinement(old, new, ["那家印刷厂的全名是衡阳长风印刷厂。"])
    assert not d4.workplace_refinement(old, new, ["后来我改在衡阳长风印刷厂工作。"])


def test_date_in_event_identifier_does_not_authorize_or_reject_facts():
    data = material("女儿2012年搬到芜湖。")
    row = fact(entity="daughter", predicate="move_year", value="2012",
               quote=data["new_answer"], event_key="daughter_move_20261014")
    trace = {}
    assert d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)["changes"]
    assert not trace["rejected_candidates"]
    row["value"] = "1999年"
    assert not d4.adapt(d4.Draft.model_validate(draft([row])), data, {})["changes"]


def test_coverage_uses_source_overlap_without_requiring_identical_punctuation():
    data = material("我家有本1979年的手写菜谱，现在还没上传，下次可以聊它。")
    row = fact(predicate="material_status", value="菜谱未上传",
               quote="我家有本1979年的手写菜谱，现在还没上传")
    raw = supported(data, row)
    raw["coverage"] = [
        {"quote": "我家有本1979年的手写菜谱，", "disposition": "facts", "candidate_ids": ["F1"]},
        {"quote": "现在还没上传，", "disposition": "facts", "candidate_ids": ["F1"]},
        {"quote": "下次可以聊它。", "disposition": "control", "candidate_ids": []},
    ]
    grounding.validate(raw, data, {}, require_coverage=True)
    raw["coverage"][2] = {"quote": "下次可以聊它。", "disposition": "facts",
                          "candidate_ids": ["F1"]}
    with pytest.raises(ValueError, match="coverage_candidate_source_mismatch"):
        grounding.validate(raw, data, {}, require_coverage=True)


def test_wrong_field_link_does_not_discard_supported_responsibility():
    old = prior()
    data = material("我在照相馆负责冲洗照片。")
    data["current_entries"] = [old]
    row = fact(predicate="work_responsibilities", value="负责冲洗照片", quote=data["new_answer"],
               entry_id=old["id"])
    trace = {}
    result = d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)
    assert result["changes"][0]["field_key"] == "work.responsibilities"
    assert result["changes"][0]["id"] is None
    assert trace["removed_cross_field_links"] == ["F1"]


def test_sentence_coverage_detects_omitted_disclosure():
    data = material("我1970年出生。我在宜昌长大。")
    raw = reviewed()
    with pytest.raises(ValueError, match="incomplete_source_coverage"):
        grounding.validate(raw, data, {}, require_coverage=True)
    raw["coverage"].append({"quote": "我在宜昌长大", "disposition": "facts", "candidate_ids": []})
    with pytest.raises(ValueError, match="unlinked_fact_coverage"):
        grounding.validate(raw, data, {}, require_coverage=True)


def test_subject_evidence_requires_antecedent_even_when_model_says_explicit():
    data = material("女儿曾住宣城。她现在是否还住那里，我不知道。")
    row = fact(entity="daughter", predicate="resides_in", value="现在是否住宣城未知",
               status="unknown", quote="她现在是否还住那里，我不知道")
    raw = supported(data, row)
    trace = {}
    assert not grounding.validate(raw, data, trace).candidates
    assert trace["grounding"]["rejected"][0]["reason"] == "missing_necessary_entity_anchor"
    raw["support_checks"][0]["components"][0]["evidence"].append(
        {"source_id": data["source_ids"][0], "quote": "女儿曾住宣城"}
    )
    final = grounding.validate(raw, data, trace)
    output = d4.adapt(final, data, trace)
    assert output["changes"]
    assert any("女儿曾住宣城" in e["quote"] for e in trace["record_evidence"]["0"])


def test_reaffirmation_keeps_one_teacher_fact_with_both_sources():
    old = prior("learning_teachers", "郭师傅教我装订", "learning.teachers[]", "person:郭师傅")
    data = material("我还是跟郭师傅学的装订。")
    data["current_entries"] = [old]
    row = fact(entity="person:郭师傅", predicate="learning_teachers", value="跟郭师傅学装订",
               quote=data["new_answer"], entry_id=old["id"])
    trace = {}
    final = grounding.validate(supported(data, row, old, "reaffirm", 0), data, trace)
    output = d4.adapt(final, data, trace)
    assert len(output["changes"][0]["value"]["facts"]) == 1
    assert {e["id"] for e in trace["record_evidence"]["0"]} == {"old", "test"}


def test_old_relation_requires_original_message_identity_not_only_same_words():
    old = prior("learning_teachers", "郭师傅教我装订", "learning.teachers[]", "person:郭师傅")
    data = material("我还是跟郭师傅学的装订。")
    data["current_entries"] = [old]
    data["retrieved_sources"] = [{"source_id": "round:other:v1", "type": "test",
                                  "id": "other", "version": 1, "quote": old["source"]["quote"]}]
    row = fact(entity="person:郭师傅", predicate="learning_teachers", value="跟郭师傅学装订",
               quote=data["new_answer"], entry_id=old["id"])
    raw = supported(data, row, old, "reaffirm", 0)
    raw["support_checks"][0]["components"][0]["evidence"][-1]["source_id"] = "round:other:v1"
    trace = {}
    assert not grounding.validate(raw, data, trace).candidates
    assert trace["grounding"]["rejected"][0]["reason"] == "missing_prior_fact_evidence"


@pytest.mark.parametrize("relation,new_value,reason", [
    ("refine", "1990年", "incompatible_fact_years"),
    ("reaffirm", "1990年", "incompatible_fact_years"),
    ("correct", "1990年", "unrequested_fact_correction"),
])
def test_relation_cannot_hide_year_conflict(relation, new_value, reason):
    old = prior("employment_start", "1987年")
    data = material("我1990年入职照相馆。")
    data["current_entries"] = [old]
    row = fact(predicate="employment_start", value=new_value, quote=data["new_answer"],
               entry_id=old["id"])
    trace = {}
    assert not grounding.validate(supported(data, row, old, relation, 0), data, trace).candidates
    assert trace["grounding"]["rejected"][0]["reason"] == reason


def test_targeted_correction_preserves_other_facts():
    old = prior("employment_start", "1987年")
    old["value"]["facts"].append({"subject": "本人", "entity_id": "self", "predicate": "workplace",
                                    "value": "照相馆", "status": "reported"})
    data = material("更正，是1988年入职照相馆。")
    data["current_entries"] = [old]
    row = fact(predicate="employment_start", value="1988年", quote=data["new_answer"],
               entry_id=old["id"])
    trace = {}
    final = grounding.validate(supported(data, row, old, "correct", 0), data, trace)
    output = d4.adapt(final, data, trace)
    assert {a["value"] for a in output["changes"][0]["value"]["facts"]} == {"1988年", "照相馆"}
    assert not trace["conflict_indices"]


def test_declined_cause_restatement_has_one_atom():
    old = prior("debt_cause", "不愿谈", "turning.hardships[]")
    old["value"]["facts"][0]["status"] = "declined"
    data = material("欠债原因我仍不愿谈。")
    data["current_entries"] = [old]
    row = fact(predicate="debt_cause", value="仍不愿谈", status="declined",
               quote=data["new_answer"], entry_id=old["id"])
    output = d4.adapt(d4.Draft.model_validate(draft([row])), data, {})
    assert len(output["changes"][0]["value"]["facts"]) == 1
    assert output["changes"][0]["state"] == "declined"


def test_year_format_difference_does_not_create_a_conflict_or_duplicate():
    old = prior("employment_start", "1987")
    data = material("我1987年入职照相馆。")
    data["current_entries"] = [old]
    row = fact(predicate="employment_start", value="1987年", quote=data["new_answer"],
               entry_id=old["id"])
    trace = {}
    output = d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)
    assert not trace["conflict_indices"]
    assert len(output["changes"][0]["value"]["facts"]) == 1


def test_two_family_move_events_are_not_a_single_conflict():
    old = prior("move_year", "2012年", "family.members[]", "daughter")
    old["value"]["facts"][0]["event_key"] = "move-first"
    data = material("女儿2020年又搬了一次家。")
    data["current_entries"] = [old]
    row = fact(entity="daughter", predicate="move_year", value="2020年",
               quote=data["new_answer"], entry_id=old["id"], event_key="move-second")
    trace = {}
    output = d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)
    assert not trace["conflict_indices"]
    assert len(output["changes"][0]["value"]["facts"]) == 2
    row["event_key"] = "move-first"
    d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)
    assert trace["conflict_indices"] == [0]


@pytest.mark.parametrize("predicate,value,quote,object_id", [
    ("host", "住在讲述者的弟弟家", "女儿住在我弟弟家。", "brother"),
    ("host", "住在我叔叔家", "女儿住在我叔叔家。", "uncle"),
    ("call_recipient", "给我打电话", "女儿给我打电话。", "self"),
    ("call_recipient", "打给我的姐姐", "女儿打给我的姐姐。", "sister"),
])
def test_supported_object_sentence_survives_format_gate(predicate, value, quote, object_id):
    data = material(quote)
    row = fact(entity="daughter", predicate=predicate, value=value, quote=quote,
               object_entity_id=object_id)
    trace = {}
    output = d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)
    assert output["changes"][0]["value"]["facts"][0]["value"] == d4.label(object_id)
    assert not trace["rejected_candidates"]
    assert trace["object_normalizations"][0]["original"] == value
    assert trace["record_evidence"]["0"][0]["quote"] == quote


@pytest.mark.parametrize("value,quote,object_id", [
    ("不住在弟弟家", "女儿不住在弟弟家。", "brother"),
    ("住在弟弟家", "女儿不是住在弟弟家。", "brother"),
    ("住在弟弟家", "女儿是否住在弟弟家，我不清楚。", "brother"),
    ("住在弟弟家", "女儿可能住在弟弟家。", "brother"),
    ("住在弟弟家", "女儿住在弟弟家？", "brother"),
    ("住在弟弟家", "女儿住在弟弟家，我不清楚。", "brother"),
    ("住在弟弟家", "女儿住在弟弟家还是姐姐家？", "brother"),
    ("住在弟弟家", "女儿住在叔叔家。", "brother"),
    ("住在弟弟家", "女儿住在弟弟家。", "uncle"),
    ("住在弟弟家并照顾他", "女儿住在弟弟家。", "brother"),
])
def test_object_repair_never_strips_negation_ambiguity_or_extra_claims(value, quote, object_id):
    data = material(quote)
    row = fact(entity="daughter", predicate="host", value=value, quote=quote,
               object_entity_id=object_id)
    trace = {}
    assert not d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)["changes"]
    assert not trace.get("object_normalizations")


def test_enhanced_reaffirmation_checks_normalized_object_without_bypassing_support():
    old = prior("host", "弟弟", "family.members[]", "daughter")
    old["source"]["quote"] = "女儿住在我弟弟家。"
    data = material("女儿仍住在我弟弟家。")
    data["current_entries"] = [old]
    row = fact(entity="daughter", predicate="host", value="住在讲述者的弟弟家",
               quote=data["new_answer"], entry_id=old["id"], object_entity_id="brother")
    raw = supported(data, row, old, "reaffirm", 0)
    raw["support_checks"][0]["components"].append(
        {"role": "object", "claim": "讲述者的弟弟", "evidence": deepcopy(row["evidence"])}
    )
    trace = {}
    final = grounding.validate(raw, data, trace)
    assert final.candidates[0].value == "弟弟"
    assert not trace["grounding"]["rejected"]
    raw["support_checks"][0]["verdict"] = "unsupported"
    assert not grounding.validate(raw, data, {}).candidates


def test_complex_negative_call_sentence_is_not_reduced_to_an_affirmative_object():
    data = material("女儿通常给我打电话，不是我给她打。")
    row = fact(entity="daughter", predicate="call_recipient", object_entity_id="self",
               value="女儿通常主动给本人打电话，而不是本人给女儿打", quote=data["new_answer"])
    trace = {}
    assert not d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)["changes"]
    assert trace["rejected_candidates"][0]["candidate"]["value"] == row["value"]
    assert not trace.get("object_normalizations")


def test_old_affirmative_relation_cannot_repair_a_current_denial():
    data = material("女儿现在不住在我弟弟家。")
    data["recent_dialogue"] = [{"id": "round:old:v1", "answer": "女儿住在我弟弟家。",
                                "question": "后来呢？"}]
    row = fact(entity="daughter", predicate="host", object_entity_id="brother",
               value="住在讲述者的弟弟家", quote=data["new_answer"])
    row["evidence"].append({"source_id": "round:old:v1", "quote": "女儿住在我弟弟家。"})
    trace = {}
    assert not d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)["changes"]
    assert not trace.get("object_normalizations")


def debt_entries():
    old = prior("debt_year", "2004年", "turning.hardships[]")
    old["value"]["facts"][0]["event_key"] = "debt-2004"
    old["value"]["facts"].extend([
        {"subject": "本人", "entity_id": "self", "predicate": "debt_cause", "value": "未披露",
         "status": "declined", "event_key": "debt-2004"},
        {"subject": "本人", "entity_id": "self", "predicate": "use_scope",
         "value": "2004年欠债这段只留内部资料", "status": "reported", "event_key": "debt-2004"},
    ])
    old["source"]["quote"] = "我2004年欠过债，原因不想讲。欠债这段只留内部资料，不写进书。"
    old["use_scope"] = "internal"
    excluded = prior("preferences_exclusions", "2004年欠债这段不写进书", "preferences.exclusions")
    excluded["value"]["facts"][0]["event_key"] = "debt-2004"
    excluded["record_key"] = "single"
    excluded["use_scope"] = "internal"
    excluded["source"] = deepcopy(old["source"])
    excluded["source_id"] = "entry:exclusion:v1"
    return old, excluded


def test_year_correction_updates_linked_restrictions_and_preserves_unrelated_facts():
    old, excluded = debt_entries()
    for entity, event in (("self", "other-event"), ("father", "debt-2004")):
        excluded["value"]["facts"].append({
            "subject": d4.label(entity), "entity_id": entity, "predicate": "preferences_exclusions",
            "value": "2004年的另一段经历不写进书", "status": "reported", "event_key": event,
        })
    original = deepcopy([old, excluded])
    data = material("把刚才欠债年份更正为2005年，其他不用改。")
    data["current_entries"] = [old, excluded]
    row = fact(predicate="debt_year", value="2005年", quote=data["new_answer"],
               entry_id=old["id"], event_key="debt-2004")
    trace = {}
    output = d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)
    by_field = {c["field_key"]: c for c in output["changes"]}
    hardship = by_field["turning.hardships[]"]["value"]["facts"]
    assert {a["predicate"]: a["value"] for a in hardship} == {
        "debt_year": "2005年", "debt_cause": "未披露", "use_scope": "2005年欠债这段只留内部资料",
    }
    restrictions = by_field["preferences.exclusions"]["value"]["facts"]
    assert restrictions[0]["value"] == "2005年欠债这段不写进书"
    assert restrictions[1:] == excluded["value"]["facts"][1:]
    assert all(c["use_scope"] == "internal" for c in output["changes"])
    assert all(a["event_key"] == "debt-2004" for a in hardship)
    assert data["current_entries"] == original
    assert {e["quote"] for e in trace["record_evidence"]["1"]} >= {
        old["source"]["quote"], data["new_answer"],
    }


@pytest.mark.parametrize("quote,value,reason", [
    ("我2005年欠过债。", "2005年", "conflict"),
    ("欠债年份更正为2005年。", "2099年", "unsupported_year"),
])
def test_unaccepted_or_unrequested_change_cannot_propagate_to_restrictions(quote, value, reason):
    old, excluded = debt_entries()
    data = material(quote)
    data["current_entries"] = [old, excluded]
    row = fact(predicate="debt_year", value=value, quote=quote,
               entry_id=old["id"], event_key="debt-2004")
    trace = {}
    d4.adapt(d4.Draft.model_validate(draft([row])), data, trace)
    assert not trace.get("linked_fact_corrections"), reason


@pytest.mark.parametrize("facts", ["2004年欠债", ["2004年欠债"], [{"predicate": "manual_note"}]])
def test_legacy_manual_values_do_not_break_sourced_date_correction(facts):
    old, excluded = debt_entries()
    excluded["value"]["facts"] = facts
    data = material("欠债年份更正为2005年。")
    data["current_entries"] = [old, excluded]
    row = fact(predicate="debt_year", value="2005年", quote=data["new_answer"],
               entry_id=old["id"], event_key="debt-2004")
    output = d4.adapt(d4.Draft.model_validate(draft([row])), data, {})
    assert len(output["changes"]) == 1
    assert excluded["value"]["facts"] == facts


def test_linked_correction_audit_tracks_changes_after_an_unrelated_rejection():
    old, excluded = debt_entries()
    data = material("我有张没上传的照片。欠债年份更正为2005年。")
    data["current_entries"] = [old, excluded]
    rows = [
        fact(predicate="materials_captions", value="有张照片", quote="我有张没上传的照片。"),
        fact(predicate="debt_year", value="2005年", quote="欠债年份更正为2005年。",
             entry_id=old["id"], event_key="debt-2004", candidate_id="F2"),
    ]
    trace = {}
    output = d4.adapt(d4.Draft.model_validate(draft(rows)), data, trace)
    assert len(output["changes"]) == 2
    for link in trace["linked_fact_corrections"]:
        assert link["root_index"] == 0
        assert output["changes"][link["change_index"]]["field_key"] in {
            "turning.hardships[]", "preferences.exclusions",
        }


@pytest.mark.parametrize("mode", ["baseline", "combined"])
def test_correction_refreshes_all_linked_values_with_original_evidence(
    client, enabled, monkeypatch, mode,  # noqa: F811
):
    monkeypatch.setattr(enabled, "interview_d4_enhancement", mode)
    person = client.post("/v1/persons", json={"display_name": "关联更正合成人物"}).json()
    session = client.post("/v1/interviews", json={"subject_id": person["id"]}).json()

    def structured(self, prompt, value, schema, **kwargs):
        data = json.loads(value)
        sid, text = data["target_source"], data["new_answer"]
        old = next((e for e in data["current_entries"]
                    if e["field_key"] == "turning.hardships[]"), None)
        rows = [fact(source=sid, predicate="debt_year", value="2005年" if old else "2004年",
                     quote=text, entry_id=old["id"] if old else None, event_key="debt-2004",
                     use_scope="internal")]
        if not old:
            rows.extend(fact(source=sid, predicate=predicate, value=content, quote=text,
                             candidate_id=f"F{i}", event_key="debt-2004", use_scope="internal",
                             status="declined" if predicate == "debt_cause" else "reported")
                        for i, (predicate, content) in enumerate((
                            ("debt_cause", "未披露"), ("use_scope", "2004年欠债只留内部资料"),
                            ("preferences_exclusions", "2004年欠债这段不写进书"),
                        ), 2))
        if self.model == "lite-test" or mode == "baseline":
            return draft(rows, source=sid)
        raw = reviewed(rows)
        raw["decision"]["used_source_ids"] = [sid]
        raw["coverage"] = [{"quote": text, "disposition": "facts",
                            "candidate_ids": [r["candidate_id"] for r in rows]}]
        raw["question_support"]["evidence"] = [{"source_id": sid, "quote": text}]
        if old:
            check = raw["support_checks"][0]
            check.update(relation="correct", prior_fact_index=0)
            check["components"][0]["evidence"].append({
                "source_id": old["source_id"], "quote": old["source"]["quote"],
            })
        return raw

    monkeypatch.setattr(OpenAICompatibleClient, "chat_structured", structured)
    original = "我2004年欠过债，原因不想讲。欠债只留内部资料，不写进书。"
    correction = "把刚才欠债年份更正为2005年，其他不用改。"
    with SessionLocal() as db:
        for turn, text in enumerate((original, correction), 1):
            result = process(db, enabled.default_tenant_id, UUID(session["profile_id"]), text,
                             {"type": "test", "id": f"debt-turn-{turn}", "version": 1}, uuid4())
            assert result["audit"]["verdict"] == "pass"
    entries = client.get(f"/v1/life-profiles/{session['profile_id']}").json()["entries"]
    for entry in entries:
        if entry["field_key"] not in {"turning.hardships[]", "preferences.exclusions"}:
            continue
        assert entry["use_scope"] == "internal"
        assert "2004年" not in entry["value"]["what"]
        assert "2005年" in entry["value"]["what"]
        assert {e["quote"] for e in entry["source"]["evidence"]} >= {original, correction}


def test_independent_review_and_refinement_persist_after_refresh(client, enabled, monkeypatch):  # noqa: F811
    monkeypatch.setattr(enabled, "interview_d4_enhancement", "combined")
    person = client.post("/v1/persons", json={"display_name": "核查持久化合成人物"}).json()
    session = client.post("/v1/interviews", json={"subject_id": person["id"]}).json()

    def structured(self, prompt, value, schema, **kwargs):
        data = json.loads(value)
        sid, text = data["target_source"], data["new_answer"]
        old = next((e for e in data["current_entries"] if e["field_key"] == "work.records[]"), None)
        row = fact(source=sid, predicate="workplace", value="江城照相馆" if old else "照相馆",
                   quote=text, event_key="job", entry_id=old["id"] if old else None)
        if self.model == "lite-test":
            return draft([row], source=sid)
        assert "candidate_draft" not in data
        assert "proposed_reply" in data
        raw = supported({**data, "source_ids": [sid]}, row, old, "refine" if old else "new",
                        0 if old else None)
        raw["decision"]["used_source_ids"] = [sid]
        return raw

    monkeypatch.setattr(OpenAICompatibleClient, "chat_structured", structured)
    with SessionLocal() as db:
        for turn, text in enumerate(("我进了照相馆。", "我工作的那家叫江城照相馆。"), 1):
            result = process(db, enabled.default_tenant_id, UUID(session["profile_id"]), text,
                             {"type": "test", "id": f"turn-{turn}", "version": 1}, uuid4())
            assert result["audit"]["verdict"] == "pass"
    entries = client.get(f"/v1/life-profiles/{session['profile_id']}").json()["entries"]
    jobs = [e for e in entries if e["field_key"] == "work.records[]"]
    assert len(jobs) == 1
    assert jobs[0]["certainty"] == "reported"
    assert [a["value"] for a in jobs[0]["value"]["facts"]] == ["江城照相馆"]
    assert {e["id"] for e in jobs[0]["source"]["evidence"]} >= {"turn-1", "turn-2"}

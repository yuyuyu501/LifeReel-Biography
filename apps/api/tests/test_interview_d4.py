"""D4 runtime and persistence regressions; synthetic providers only."""

import json
from copy import deepcopy
from uuid import UUID, uuid4

import httpx
import pytest
from lifereel_api.modules.interview import d4
from lifereel_api.modules.interview.profile_extraction import process
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal


def material(text="我1970年出生，我父亲1940年出生。"):
    return {
        "new_answer": text,
        "source_ids": ["current:test:v1"],
        "current_source": {"type": "test", "id": "test", "version": 1},
        "current_entries": [],
        "recent_dialogue": [],
        "recent_questions": [],
    }


def fact(
    source="current:test:v1",
    entity="self",
    predicate="birth_year",
    value="1970年",
    quote="我1970年出生",
    **extra,
):
    return {
        "candidate_id": "F1",
        "entity_id": entity,
        "entity_candidates": [entity],
        "resolution": "explicit",
        "predicate": predicate,
        "value": value,
        "status": "reported",
        "object_entity_id": None,
        "evidence": [{"source_id": source, "quote": quote}],
        "binding_evidence": [{"source_id": source, "quote": quote}],
        "entry_id": None,
        "event_key": "birth",
        "use_scope": "works",
        "pseudonyms": [],
        **extra,
    }


def draft(rows, source="current:test:v1", **extra):
    return {
        "candidates": rows,
        "pending": [],
        "review_log": [],
        "next_question": "您小时候最常和谁一起玩？",
        "decision": {
            "action": "deepen_scene",
            "used_source_ids": [source],
            "question_goal": "了解童年玩伴",
            "topic": "童年",
            "boundary_quote": "",
            "history_request": None,
        },
        **extra,
    }


@pytest.fixture
def enabled(monkeypatch):
    settings = get_settings()
    for key, value in {
        "interview_recording_method": "d4",
        "interview_enhancements_enabled": True,
        "interview_review_enabled": True,
        "interview_history_enabled": False,
        "llm_provider": "openai-compatible",
        "interview_llm_backend": "inherit",
        "openai_compatible_base_url": "https://synthetic.invalid/v1",
        "openai_compatible_api_key": "synthetic",
        "interview_llm_model": "lite-test",
        "interview_review_llm_model": "sol-test",
    }.items():
        monkeypatch.setattr(settings, key, value)
    return settings


def test_entity_mapping_and_evidence_spans():
    data = material()
    rows = [
        fact(),
        fact(entity="father", value="1940年", quote="我父亲1940年出生", candidate_id="F2"),
    ]
    trace = {}
    output = d4.adapt(d4.Draft.model_validate(draft(rows)), data, trace)
    assert output["changes"][0]["field_key"] == "identity.birth_time"
    assert output["changes"][1]["field_key"] == "family.members[]"
    assert output["changes"][1]["value"]["facts"][0]["entity_id"] == "father"
    assert trace["record_evidence"]["1"][0]["start"] == data["new_answer"].index("我父亲")


@pytest.mark.parametrize(
    "extra,reason",
    [
        ({"entity_candidates": ["self", "father"]}, "unresolved_entity"),
        ({"evidence": [{"source_id": "current:test:v1", "quote": "编造原话"}]}, "invalid_quote"),
        ({"binding_evidence": []}, "missing_binding_quote"),
        ({"predicate": "closure_year"}, "closure_actor_is_person"),
        ({"entry_id": str(uuid4())}, "invalid_entry_link"),
        ({"use_scope": "pseudonym"}, "missing_pseudonym"),
    ],
)
def test_gates_reject_without_persisting(extra, reason):
    trace = {}
    output = d4.adapt(d4.Draft.model_validate(draft([fact(**extra)])), material(), trace)
    assert not output["changes"]
    assert trace["rejected_candidates"][0]["reason"] == reason
    assert trace["fact_ledger"][0]["status"] == "pending"


def test_cross_message_actor_binding_and_metadata_scope():
    data = material("后来搬到长沙。照片还没上传。")
    data["recent_dialogue"] = [
        {"id": "round:old:v1", "answer": "我父亲2001年搬家。", "question": "后来呢？"}
    ]
    row = fact(
        entity="father",
        predicate="moved_to",
        value="长沙",
        quote="后来搬到长沙。",
        resolution="contextual",
        binding_evidence=[{"source_id": "round:old:v1", "quote": "我父亲2001年搬家。"}],
    )
    metadata = fact(
        candidate_id="F2",
        predicate="material_status",
        value="照片还没上传",
        quote="照片还没上传",
        resolution="contextual",
    )
    trace = {}
    output = d4.adapt(d4.Draft.model_validate(draft([row, metadata])), data, trace)
    assert [c["field_key"] for c in output["changes"]] == [
        "family.members[]",
        "legacy.open_threads",
    ]
    assert len(trace["record_evidence"]["0"]) == 2


def test_sol_rebuilds_and_fills_empty_profile(client, enabled, monkeypatch):
    person = client.post("/v1/persons", json={"display_name": "D4合成人物"}).json()
    session = client.post("/v1/interviews", json={"subject_id": person["id"]}).json()
    calls = []

    def structured(self, prompt, value, schema):
        data = json.loads(value)
        calls.append(self.model)
        sid = data["target_source"]
        rows = [fact(source=sid)]
        if self.model == "sol-test":
            assert len(data["candidate_draft"]["candidates"]) == 1
            rows.append(
                fact(
                    source=sid,
                    entity="father",
                    value="1940年",
                    quote="我父亲1940年出生",
                    candidate_id="F2",
                )
            )
        return draft(rows, source=sid)

    monkeypatch.setattr(OpenAICompatibleClient, "chat_structured", structured)
    request = uuid4()
    with SessionLocal() as db:
        result = process(
            db,
            enabled.default_tenant_id,
            UUID(session["profile_id"]),
            material()["new_answer"],
            {"type": "test", "id": "test", "version": 1},
            request,
        )
        replay = process(
            db,
            enabled.default_tenant_id,
            UUID(session["profile_id"]),
            material()["new_answer"],
            {"type": "test", "id": "test", "version": 1},
            request,
        )
    assert calls == ["lite-test", "sol-test"]
    entries = result["profile"]["entries"]
    assert any(e["field_key"] == "identity.birth_time" and e["value"] == "1970年" for e in entries)
    assert any(
        e["field_key"] == "family.members[]" and "1940年" in e["value"]["what"] for e in entries
    )
    assert replay["profile"]["version_number"] == result["profile"]["version_number"]
    assert result["audit"]["recording_method"] == d4.VERSION
    assert all(t["status"] == "saved" for f in result["audit"]["fact_ledger"] for t in f["targets"])


def test_sol_timeout_fails_closed_without_retry(enabled, monkeypatch):
    calls = []

    def structured(self, *args):
        calls.append(self.model)
        if self.model == "sol-test":
            raise httpx.ReadTimeout("synthetic")
        return draft([fact()])

    monkeypatch.setattr(OpenAICompatibleClient, "chat_structured", structured)
    output, trace = d4.generate(OpenAICompatibleClient.for_task("interview"), material())
    assert not output["changes"] and trace["verdict"] == "fallback"
    assert trace["transport_uncertain"]
    assert calls == ["lite-test", "sol-test"]


def test_sol_reconstructs_invalid_lite_schema(enabled, monkeypatch):
    def structured(self, prompt, data, schema):
        if self.model == "lite-test":
            return {"invalid": True}
        assert json.loads(data)["upstream_error"] == "invalid_lite_schema"
        return draft([fact()])

    monkeypatch.setattr(OpenAICompatibleClient, "chat_structured", structured)
    output, trace = d4.generate(OpenAICompatibleClient.for_task("interview"), material())
    assert output["changes"][0]["value"] == "1970年" and trace["verdict"] == "pass"


def test_atomic_correction_preserves_other_facts_and_internal_scope():
    data = material("更正一下，我是1991年入职的。")
    old = {
        "id": str(uuid4()),
        "field_key": "work.records[]",
        "record_key": "old-job",
        "value": {
            "what": "旧经历",
            "facts": [
                {
                    "subject": "本人",
                    "entity_id": "self",
                    "predicate": "employment_start",
                    "value": "1990年",
                    "status": "reported",
                },
                {
                    "subject": "本人",
                    "entity_id": "self",
                    "predicate": "workplace",
                    "value": "图书馆",
                    "status": "reported",
                },
            ],
        },
        "state": "filled",
        "certainty": "reported",
        "use_scope": "internal",
        "source": {"type": "test", "id": "old", "version": 1, "quote": "我1990年进图书馆。"},
    }
    data["current_entries"] = [old]
    row = fact(
        predicate="employment_start", value="1991年", quote=data["new_answer"], entry_id=old["id"]
    )
    output = d4.adapt(d4.Draft.model_validate(draft([row])), data, {})
    change = output["changes"][0]
    assert "1990年" not in change["value"]["what"]
    assert "图书馆" in change["value"]["what"] and change["use_scope"] == "internal"
    assert change["id"] == old["id"] and change["record_key"] == old["record_key"]
    assert old["value"]["facts"][0]["value"] == "1990年"


def test_strict_schema_has_fixed_predicates_and_no_open_objects():
    schema = d4.strict_schema()
    assert "employment_start" in schema["$defs"]["Candidate"]["properties"]["predicate"]["enum"]

    def check(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value["properties"])
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(deepcopy(schema))


def test_family_person_record_groups_distinct_atomic_topics():
    rows = [
        fact(entity="father", value="1940年", quote="我父亲1940年出生", event_key="birth"),
        fact(
            entity="father",
            predicate="alive",
            value="现在还健在",
            quote="他现在还健在",
            candidate_id="F2",
            event_key="alive",
        ),
    ]
    data = material("我父亲1940年出生，他现在还健在。")
    output = d4.adapt(d4.Draft.model_validate(draft(rows)), data, {})
    assert len(output["changes"]) == 1
    assert len(output["changes"][0]["value"]["facts"]) == 2


def test_repeated_event_without_explicit_link_preserves_old_atoms():
    row = fact(predicate="workplace", value="图书馆", quote="我进了图书馆。", event_key="job")
    initial = d4.adapt(d4.Draft.model_validate(draft([row])), material("我进了图书馆。"), {})
    old = {
        **initial["changes"][0],
        "id": str(uuid4()),
        "source": {"type": "test", "id": "old", "quote": "我进了图书馆。", "version": 1},
    }
    data = material("我1991年入职。")
    data["current_entries"] = [old]
    row = fact(
        predicate="employment_start", value="1991年", quote=data["new_answer"], event_key="job"
    )
    output = d4.adapt(d4.Draft.model_validate(draft([row])), data, {})
    assert output["changes"][0]["id"] == old["id"]
    assert "图书馆" in output["changes"][0]["value"]["what"]


def test_mixed_stop_preserves_facts_and_never_asks_after_stop():
    data = material("我1970年出生。今天先聊到这里。")
    output = d4.adapt(d4.Draft.model_validate(draft([fact()])), data, {})
    assert output["changes"] and output["decision"]["action"] == "close"
    assert "？" not in output["next_question"]


def test_employment_date_conflict_is_flagged_before_persistence():
    initial = d4.adapt(
        d4.Draft.model_validate(
            draft(
                [
                    fact(
                        predicate="employment_start",
                        value="1990年",
                        quote="我1990年入职。",
                        event_key="job",
                    )
                ]
            )
        ),
        material("我1990年入职。"),
        {},
    )
    old = {
        **initial["changes"][0],
        "id": str(uuid4()),
        "source": {"type": "test", "id": "old", "quote": "我1990年入职。", "version": 1},
    }
    data = material("我1991年入职。")
    data["current_entries"] = [old]
    trace = {}
    d4.adapt(
        d4.Draft.model_validate(
            draft(
                [
                    fact(
                        predicate="employment_start",
                        value="1991年",
                        quote=data["new_answer"],
                        event_key="job",
                    )
                ]
            )
        ),
        data,
        trace,
    )
    assert trace["conflict_indices"] == [0]

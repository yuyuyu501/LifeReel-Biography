"""Grounding contracts, exact evidence and database scope; no live providers."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from lifereel_api.modules.interview import d4, grounding, quality, retrieval
from lifereel_api.modules.interview.models import InterviewRound
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient
from test_interview_d4 import draft, fact, material

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal


def reviewed(rows=None):
    rows = rows if rows is not None else [fact()]
    return {
        **draft(rows),
        "support_checks": [
            {
                "candidate_id": r["candidate_id"],
                "verdict": "supported",
                "reason": "",
                "components": [
                    {"role": role, "claim": "核对要素", "evidence": deepcopy(r["binding_evidence"])}
                    for role in ("actor", "action", "time", "topic", "polarity")
                ],
            }
            for r in rows
        ],
        "question_support": {
            "goal": "了解童年玩伴",
            "anchor": "出生年份",
            "evidence": [{"source_id": "current:test:v1", "quote": "我1970年出生"}],
        },
        "coverage": [{"quote": "我1970年出生", "disposition": "facts",
                      "candidate_ids": [r["candidate_id"] for r in rows]}],
    }


def source(index, answer):
    return {"id": f"round:{index}:v1", "record_id": index, "version": 1, "answer": answer}


def test_missing_and_duplicate_checks_fail_closed():
    raw = reviewed()
    raw["support_checks"] = []
    with pytest.raises(ValueError, match="incomplete_support_checks"):
        grounding.validate(raw, material(), {})
    raw = reviewed()
    raw["support_checks"] *= 2
    with pytest.raises(ValueError, match="incomplete_support_checks"):
        grounding.validate(raw, material(), {})


def test_check_does_not_authorize_nonexistent_source():
    raw = reviewed()
    raw["support_checks"][0]["components"][0]["evidence"][0]["source_id"] = "round:other:v1"
    trace = {}
    result = grounding.validate(raw, material(), trace)
    assert not result.candidates
    assert trace["grounding"]["rejected"][0]["reason"] == "invalid_support_quote"


def test_unsupported_fact_not_written_even_when_quote_exists():
    raw = reviewed()
    raw["support_checks"][0]["verdict"] = "unsupported"
    trace = {}
    result = grounding.validate(raw, material(), trace)
    assert not d4.adapt(result, material(), {})["changes"]
    assert trace["grounding"]["rejected"][0]["reason"] == "unsupported"


def test_receiver_requires_separate_object_support():
    data = material("女儿每周给我打电话。")
    row = fact(
        entity="daughter",
        predicate="call_recipient",
        value="本人",
        object_entity_id="self",
        quote=data["new_answer"],
    )
    raw = reviewed([row])
    raw["question_support"]["evidence"][0]["quote"] = data["new_answer"]
    result = grounding.validate(raw, data, {})
    assert not result.candidates
    raw["support_checks"][0]["components"].append(
        {
            "role": "object",
            "claim": "本人",
            "evidence": row["evidence"],
        }
    )
    assert grounding.validate(raw, data, {}).candidates[0].entity_id == "daughter"


def test_necessary_history_is_attached_to_persistable_evidence():
    data = material("原因不讲。")
    data["retrieved_sources"] = [
        {
            "source_id": "round:old:v2",
            "type": "interview_round",
            "id": "old",
            "version": 2,
            "quote": "我2003年欠过债。",
        }
    ]
    row = fact(predicate="debt_cause", value="未披露", status="declined", quote="原因不讲。")
    raw = reviewed([row])
    raw["support_checks"][0]["components"].append(
        {
            "role": "topic",
            "claim": "欠债原因",
            "evidence": [{"source_id": "round:old:v2", "quote": "我2003年欠过债。"}],
        }
    )
    raw["question_support"]["evidence"][0]["quote"] = data["new_answer"]
    trace = {}
    output = d4.adapt(grounding.validate(raw, data, trace), data, trace)
    assert output["changes"][0]["state"] == "declined"
    assert {e["id"] for e in trace["record_evidence"]["0"]} == {"test", "old"}


def test_retrieval_preserves_offsets_and_program_owned_version():
    text = "闲话。" * 1000 + "我在织布厂跟马师傅学修机器。"
    found = retrieval.select_sources([source("old", text)], "马师傅教我修机器")
    assert len(found) == 1 and found[0]["start"] > 0
    data = material()
    data["retrieved_sources"] = found
    citation = d4.citations(
        [d4.Evidence(source_id="round:old:v1", quote="马师傅")], quality.source_catalog(data)
    )[0]
    assert citation["start"] == text.index("马师傅") and citation["version"] == 1


def test_adjacent_antecedent_is_retrieved_without_unrelated_history():
    rows = [
        source("a", "我1993年进织布厂。"),
        source("b", "马师傅教我修机器。"),
        source("c", "先说别的。"),
        source("d", "今天吃了面条。"),
        source("e", "院里有盆花。"),
    ]
    found = retrieval.select_sources(rows, "马师傅")
    assert {s["id"] for s in found} == {"a", "b", "c"}
    assert all("马师傅" not in s["quote"] or s["id"] == "b" for s in found)


def test_current_corrected_entry_and_limits_remain_intact():
    old = {
        "id": str(uuid4()),
        "version_number": 3,
        "field_key": "work.records[]",
        "value": {"what": "织布厂1994年入职"},
        "state": "filled",
        "certainty": "confirmed",
        "use_scope": "internal",
        "record_key": "job",
        "pseudonyms": {},
        "source": {
            "type": "interview_round",
            "id": "old",
            "version": 2,
            "quote": "更正，是1994年入职织布厂。",
        },
    }
    before = deepcopy(old)
    enriched = retrieval.enrich_material(
        material("织布厂那段接着聊。"), [old], [source("old", "更正，是1994年入职织布厂。")]
    )
    record = enriched["current_entries"][0]
    assert record["version_number"] == 3 and record["certainty"] == "confirmed"
    assert record["use_scope"] == "internal" and old == before


def test_retrieval_never_reads_another_person_or_old_answer_revision(client):
    people = [
        client.post("/v1/persons", json={"display_name": f"检索合成人物{i}"}).json()
        for i in range(2)
    ]
    sessions = [client.post("/v1/interviews", json={"subject_id": p["id"]}).json() for p in people]
    settings = get_settings()
    with SessionLocal() as db:
        rows = []
        for index, session in enumerate(sessions):
            row = InterviewRound(
                tenant_id=settings.default_tenant_id,
                session_id=UUID(session["id"]),
                round_index=2,
                question_text="后来呢？",
                answer_version=2,
                answer_text=f"马师傅教人物{index}修机器。",
                answer_revisions=[{"version": 1, "answer_text": "旧的错误信息"}],
            )
            db.add(row)
            rows.append(row)
        db.commit()
        enriched = retrieval.enrich(
            db, settings.default_tenant_id, UUID(sessions[0]["profile_id"]), material("马师傅"), []
        )
        assert len(enriched["retrieved_sources"]) == 1
        assert enriched["retrieved_sources"][0]["id"] == str(rows[0].id)
        assert enriched["retrieved_sources"][0]["version"] == 2
        assert "错误" not in str(enriched["retrieved_sources"])
        foreign = retrieval.enrich(db, uuid4(), UUID(sessions[0]["profile_id"]), material(), [])
        assert not foreign["retrieved_sources"]


def test_no_match_is_reported_without_invented_sources():
    enriched = retrieval.enrich_material(
        material("我想聊一段别的经历"), [], [source("old", "1973年出生")], truncated=True
    )
    assert enriched["retrieval"]["history_truncated"]
    assert not enriched["retrieved_sources"]


def test_extended_schema_is_strict_and_baseline_does_not_change():
    schema = d4.strict_schema(grounding.ReviewedDraft)
    assert "support_checks" in schema["required"]
    assert "support_checks" not in d4.strict_schema()["required"]
    for value in [schema, *schema["$defs"].values()]:
        if value.get("type") == "object":
            assert value["additionalProperties"] is False
            assert set(value["required"]) == set(value["properties"])


@pytest.mark.parametrize("mode", ["baseline", "reasoning", "retrieval", "combined"])
def test_runtime_modes_have_distinct_review_contracts(monkeypatch, mode):
    settings = get_settings()
    monkeypatch.setattr(settings, "interview_review_enabled", True)
    monkeypatch.setattr(settings, "openai_compatible_base_url", "https://synthetic.invalid/v1")
    monkeypatch.setattr(settings, "openai_compatible_api_key", "synthetic")
    monkeypatch.setattr(settings, "interview_llm_model", "lite-test")
    monkeypatch.setattr(settings, "interview_review_llm_model", "sol-test")
    calls = []

    def structured(self, prompt, data, schema, **kwargs):
        calls.append(self.model)
        import json

        assert "event_action" not in json.loads(data)["atomic_predicates"]
        enhanced = mode in {"reasoning", "combined"} and self.model == "sol-test"
        assert ("support_checks" in schema["required"]) == enhanced
        assert kwargs == ({"max_output_tokens": 8192} if enhanced else {})
        return reviewed() if enhanced else draft([fact()])

    monkeypatch.setattr(OpenAICompatibleClient, "chat_structured", structured)
    output, trace = d4.generate(OpenAICompatibleClient.for_task("interview"),
                                material("我1970年出生"),
                                enhancement=mode)
    assert output["changes"][0]["value"] == "1970年"
    assert trace["verdict"] == "pass" and trace["enhancement"] == mode
    assert calls == ["lite-test", "sol-test"]


@pytest.mark.parametrize("text,action", [
    ("我1970年出生，今天先聊到这里。", "close"),
    ("我1970年出生，我们先暂停。", "pause"),
])
def test_empty_control_reply_preserves_verified_facts(monkeypatch, text, action):
    settings = get_settings()
    monkeypatch.setattr(settings, "interview_review_enabled", True)
    monkeypatch.setattr(settings, "openai_compatible_base_url", "https://synthetic.invalid/v1")
    monkeypatch.setattr(settings, "openai_compatible_api_key", "synthetic")
    monkeypatch.setattr(settings, "interview_llm_model", "lite-test")
    monkeypatch.setattr(settings, "interview_review_llm_model", "sol-test")

    def structured(self, prompt, data, schema):
        raw = draft([fact()])
        raw["next_question"] = ""
        raw["decision"]["action"] = action
        return raw

    monkeypatch.setattr(OpenAICompatibleClient, "chat_structured", structured)
    output, trace = d4.generate(OpenAICompatibleClient.for_task("interview"), material(text),
                                enhancement="baseline")
    assert output["changes"][0]["value"] == "1970年"
    assert output["decision"]["action"] == action
    assert trace["verdict"] == "pass" and trace["reply_fallback"]
    assert trace["control_reply_normalizations"] == ["lite", "sol"]


def test_model_close_does_not_authorize_blank_reply_without_user_boundary():
    raw = draft([fact()])
    raw["next_question"] = ""
    raw["decision"]["action"] = "close"
    trace = {}
    normalized = d4.normalize_control_reply(raw, material(), trace, "sol")
    with pytest.raises(ValueError):
        d4.Draft.model_validate(normalized)
    assert not trace


def test_inactive_pending_does_not_override_neutral_transition():
    data = material("这个细节我记不清了。")
    raw = draft([])
    raw["pending"] = [{
        "entity_candidates": ["self"],
        "reason": "未确定具体忘记的内容，保留原待核事项，暂不追问。",
        "question": "",
        "evidence": [{"source_id": "current:test:v1", "quote": data["new_answer"]}],
    }]
    raw["next_question"] = "我们先放一放，您有没有其他愿意讲的经历？"
    raw["decision"]["action"] = "transition"
    trace = {}
    output = d4.adapt(d4.Draft.model_validate(raw), data, trace)
    assert output["next_question"] == raw["next_question"]
    assert output["decision"]["action"] == "transition" and trace["pending"]
    assert not output["changes"]

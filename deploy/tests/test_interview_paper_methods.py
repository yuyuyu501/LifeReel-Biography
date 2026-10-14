"""Validate experimental controls and scoring, without provider calls."""

from copy import deepcopy

from interview_paper_cases import CASES
from interview_paper_methods import evidence_valid, public_input, retrieve, score


def output_fact(gold, sources):
    return {
        **{k: gold[k] for k in ("subject", "predicate", "value", "status")},
        "fields": [gold["field"]],
        "primary_field": gold["field"],
        "evidence": [
            {
                "source_id": source_id,
                "quote": next(s["text"] for s in sources if s["id"] == source_id),
            }
            for source_id in gold["sources"]
        ],
    }


def test_gold_and_case_labels_are_not_sent_to_models():
    data = public_input(CASES[0])
    assert "gold" not in data and "category" not in data and "must_abstain" not in data
    assert data["target_source"] == "U2"


def test_wrong_person_and_missing_cross_turn_source_do_not_pass():
    item = CASES[0]
    row = output_fact(item["gold"][0], item["sources"])
    row["evidence"] = row["evidence"][1:]
    result = {"status": "ok", "output": {"facts": [row]}}
    metrics = score(result, item)
    assert metrics["recovered"] == 1 and metrics["evidence_complete"] == 0
    row["subject"] = "弟弟"
    assert score(result, item)["recovered"] == 0


def test_duplicates_do_not_increase_recall_and_wrong_field_is_separate():
    item = CASES[0]
    row = output_fact(item["gold"][0], item["sources"])
    row["fields"] = ["identity.birth_time"]
    result = {"status": "ok", "output": {"facts": [row, deepcopy(row)]}}
    metrics = score(result, item)
    assert metrics["recovered"] == 1 and metrics["duplicates"] == 1
    assert metrics["field_correct"] == 0


def test_quote_substring_is_not_semantic_evidence_by_itself():
    item = CASES[0]
    row = output_fact(item["gold"][0], item["sources"])
    result = {"status": "ok", "output": {"facts": [row]}}
    review = {"pairs": {"0": 0}, "evidence_supported": []}
    assert score(result, item, review)["evidence_complete"] == 0
    assert not evidence_valid([{"source_id": "U1", "quote": "父亲去长沙"}], item["sources"])


def test_ambiguity_requires_valid_abstention_and_no_guessed_person():
    item = CASES[3]
    result = {
        "status": "ok",
        "output": {
            "facts": [],
            "abstentions": [
                {
                    "reason": "他指谁尚需澄清",
                    "evidence": [{"source_id": "U2", "quote": "他2015年"}],
                },
            ],
        },
    }
    assert score(result, item)["abstain_ok"] == 1
    result["output"]["abstentions"][0]["evidence"][0]["source_id"] = "NO_SOURCE"
    assert score(result, item)["abstain_ok"] == 0


def test_failure_keeps_disclosed_facts_in_denominator():
    metrics = score({"status": "failed"}, CASES[0])
    assert metrics["gold"] == 5 and metrics["recovered"] == 0 and metrics["success"] == 0


def test_retrieval_returns_original_sources_in_order_and_keeps_latest():
    sources = [{"id": f"U{i}", "text": "天气"} for i in range(1, 10)]
    sources[0]["text"] = "父亲 搬家 长沙"
    index = {
        "index": [{"source_id": "U1", "keywords": "爸爸 父亲 搬家", "time_keys": []}],
        "query": "爸爸 搬家",
    }
    selected = retrieve(sources, index, limit=1)
    assert selected == [sources[0], sources[-2], sources[-1]]
    assert all(s in sources for s in selected)

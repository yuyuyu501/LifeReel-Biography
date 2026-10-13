"""Produce auditable evidence and metrics; semantic marks are supplied by the reviewer."""

import argparse
import json
import math
from pathlib import Path

from interview_persona import EMPTY_FIELDS, PACKETS


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else None


def is_ordinary(turn, phase):
    if phase == "adaptive" and turn["packet_id"] in {"A11", "A12"}:
        return False
    return turn["case"] not in {"history", "pause", "close", "refusal_privacy", "ambiguity"}


def report(directory):
    profile = read(directory / "final-profile.json")
    state = read(directory / "state.json")
    turns = [
        json.loads(line)
        for line in (directory / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    entries = profile["entries"]
    lines = [f"# {state['model']} / {state['phase']}", "", "## 逐轮结果", ""]
    for turn in turns:
        audit = turn["result"].get("audit", {})
        lines.extend(
            [
                f"### {turn['packet_id']} ({turn['status']}, {turn['seconds']}s)",
                f"用户：{turn['answer']}",
                f"AI：{turn['reply']}",
                f"审核：{audit.get('verdict')}，剔除：{audit.get('dropped_changes', 0)}，"
                f"重写：{audit.get('rewrites', 0)}，回退：{audit.get('reply_fallback', False)}",
                "",
            ]
        )
    lines.extend(["## 最终67字段", ""])
    for field in profile["fields"]:
        key = field["key"]
        lines.extend([f"### {key} / {field['label']}", ""])
        for entry in (e for e in entries if e["field_key"] == key):
            lines.extend(
                [
                    f"- ID：{entry['id']}; 状态：{entry['state']}/{entry['certainty']}; "
                    f"范围：{entry['use_scope']}",
                    "- 值：" + json.dumps(entry["value"], ensure_ascii=False),
                    "- 出处：" + json.dumps(entry["source"], ensure_ascii=False),
                    "",
                ]
            )
    (directory / "evidence.md").write_text("\n".join(lines), encoding="utf-8")
    ordinary_attempts = [
        t["seconds"] for t in turns if t["seconds"] is not None if is_ordinary(t, state["phase"])
    ]
    ordinary = [
        t["seconds"]
        for t in turns
        if t["status"] == "completed"
        and t["seconds"] is not None
        and is_ordinary(t, state["phase"])
    ]
    metrics = {
        "turns": len(turns),
        "completed": sum(t["status"] == "completed" for t in turns),
        "first_attempt_completion_rate": sum(t["status"] == "completed" for t in turns)
        / len(turns),
        "ordinary_p50_seconds": percentile(ordinary, 0.5),
        "ordinary_p95_seconds": percentile(ordinary, 0.95),
        "ordinary_successful_turns": len(ordinary),
        "ordinary_attempt_p95_until_outcome": percentile(ordinary_attempts, 0.95),
        "latency_method": "nearest_rank; submission through reviewed reply and persisted profile",
        "saved_entries_count": len(entries),
        "usable_entries_count": profile["readiness"]["usable_entries"],
        "template_fields": len(profile["fields"]),
        "empty_materials": all(
            e["state"] != "filled" for e in entries if e["field_key"] in EMPTY_FIELDS
        ),
        "semantic_evaluation_complete": False,
    }
    if state["phase"] == "adaptive":
        elicited = set()
        fallback_elicited = set()
        previously_disclosed = set()
        for index, turn in enumerate(turns):
            fact_ids = set(turn["fact_ids"])
            if turn["disclosure"] == "answer_to_ai":
                previous_audit = turns[index - 1]["result"].get("audit", {}) if index else {}
                target = elicited if previous_audit.get("verdict") == "pass" else fallback_elicited
                target.update(fact_ids - previously_disclosed)
            previously_disclosed.update(fact_ids)
        metrics["annotated_new_pairs_elicited_by_ai"] = sorted(elicited)
        metrics["annotated_new_pair_count"] = len(elicited)
        metrics["annotated_new_pairs_after_application_fallback"] = sorted(fallback_elicited)
        metrics["elicitation_count_note"] = (
            "Reviewer-annotated gold fact/field pairs in answers to AI only; "
            "not a complete count of all narrative details or a standalone quality score"
        )
    calls_path = directory / "model-calls.jsonl"
    if calls_path.exists():
        calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]
        metrics["transport_calls"] = len(calls)
        metrics["transport_failures"] = sum(
            bool(c.get("error_class")) or c.get("http_status", 200) >= 400 for c in calls
        )
        metrics["reported_tokens"] = {
            key: sum((c.get("usage") or {}).get(key, 0) or 0 for c in calls)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        metrics["cost_status"] = "No verified channel price; token totals are not a currency cost"
    field_path = directory / "field-review.json"
    if field_path.exists():
        review = read(field_path)
        disclosed_packets = {t["packet_id"] for t in turns}
        expected = {p["id"]: p["facts"] for p in PACKETS if p["id"] in disclosed_packets}
        if set(review["packet_marks"]) != set(expected):
            raise ValueError("Every disclosed packet needs an explicit field review")
        marks = []
        for packet_id, facts in expected.items():
            packet_marks = review["packet_marks"][packet_id]
            if len(packet_marks) != len(facts) or set(packet_marks) - {"C", "W", "M"}:
                raise ValueError(f"Invalid field review: {packet_id}")
            for fact, mark in zip(facts, packet_marks, strict=True):
                marks.append({**fact, "mark": mark})
        metrics.update(
            field_evaluation_complete=True,
            expected_field_fact_pairs=len(marks),
            correct_field_fact_pairs=sum(m["mark"] == "C" for m in marks),
            field_recall=sum(m["mark"] == "C" for m in marks) / len(marks),
            disclosed_pair_recall=sum(m["mark"] != "M" for m in marks) / len(marks),
            precision_status=review["precision_status"],
            field_review=review,
        )
        (directory / "field-marks.json").write_text(
            json.dumps(marks, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    semantic_path = directory / "semantic-marks.json"
    if semantic_path.exists():
        marks = read(semantic_path)
        disclosed = {
            f["id"]
            for p in PACKETS
            for f in p["facts"]
            if any(t["packet_id"] == p["id"] for t in turns)
        }
        facts = marks["facts"]
        if set(facts) != disclosed:
            raise ValueError("Each disclosed fact must have an explicit semantic mark")
        generated = {e["id"] for e in entries if e["source"].get("type") == "interview_round"}
        if {m["entry_id"] for m in marks["claims"]} != generated:
            raise ValueError("Each saved interview entry must have a semantic claim count")
        supported = sum(m["supported"] for m in marks["claims"])
        unsupported = sum(m["unsupported"] for m in marks["claims"])
        metrics.update(
            semantic_evaluation_complete=True,
            expected_field_fact_pairs=len(disclosed),
            field_recall=sum(m["correct_field"] for m in facts.values()) / len(facts),
            disclosed_recall=sum(m["present"] for m in facts.values()) / len(facts),
            precision=supported / (supported + unsupported) if supported + unsupported else None,
            supported_claims=supported,
            unsupported_claims=unsupported,
            qualitative=marks["qualitative"],
            hard_cases=marks["hard_cases"],
        )
    (directory / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(metrics, ensure_ascii=False))


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    report(args.directory)

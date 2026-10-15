"""Inspect all saved atoms; scores require explicit semantic review decisions."""

import argparse
import json
from collections import defaultdict
from math import ceil
from pathlib import Path
from statistics import median

from interview_grounding_cases import CASES


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def saved_atoms(result):
    rows = []
    audit = result["audit"]
    for index, change in enumerate(result["output"]["changes"]):
        value = change["value"]
        atoms = value.get("facts", []) if isinstance(value, dict) else []
        if not atoms:
            atoms = [
                {
                    "entity_id": "self",
                    "predicate": change["field_key"].replace(".", "_"),
                    "value": value,
                    "status": change["state"],
                }
            ]
        for atom in atoms:
            rows.append(
                {
                    "index": len(rows),
                    "change_index": index,
                    "entity": atom["entity_id"],
                    "predicate": atom["predicate"],
                    "value": atom["value"],
                    "status": atom["status"],
                    "field": change["field_key"],
                    "scope": change["use_scope"],
                    "evidence": audit.get("record_evidence", {}).get(str(index), []),
                }
            )
    return rows


def inspect(out, cases):
    for path in sorted((out / "recording").glob("*/*/result.json")):
        result = read(path)
        if cases and result["case"] not in cases:
            continue
        print(
            json.dumps(
                {
                    "id": f"{result['group']}/{result['case']}",
                    "verdict": result["audit"]["verdict"],
                    "atoms": [
                        {
                            **row,
                            "evidence": [[e.get("id"), e.get("quote")] for e in row["evidence"]],
                        }
                        for row in saved_atoms(result)
                    ],
                    "pending": result["audit"].get("pending", []),
                    "rejected": result["audit"].get("rejected_candidates", []),
                    "question": result["output"]["next_question"],
                    "fallback": result["audit"].get("reply_fallback", False),
                },
                ensure_ascii=False,
            )
        )


def inspect_interviews(out, groups, turns=None):
    for directory in sorted((out / "interview").glob("*")):
        if groups and directory.name not in groups:
            continue
        previous = {}
        for path in sorted(directory.glob("turn-*/result.json")):
            record = read(path)
            result = record["result"]
            entries = result["profile"]["entries"]
            def snapshot(entry):
                return {
                    k: entry[k]
                    for k in ("field_key", "value", "state", "certainty", "use_scope", "source")
                }

            changed = [
                {k: entry[k] for k in ("field_key", "value", "state", "certainty", "use_scope")}
                for entry in entries
                if (entry["field_key"], entry["record_key"]) not in previous
                or previous[(entry["field_key"], entry["record_key"])] != snapshot(entry)
            ]
            previous = {(e["field_key"], e["record_key"]): snapshot(e) for e in entries}
            if turns and record["turn"] not in turns:
                continue
            print(
                json.dumps(
                    {
                        "id": f"{directory.name}/{record['turn']}",
                        "question": record["question"],
                        "answer": record["answer"],
                        "topic": record["topic"],
                        "tester_initiated": record["tester_initiated"],
                        "verdict": result["audit"].get("verdict"),
                        "next_question": result["next_question"],
                        "changed_entries": changed,
                        "fallback": result["audit"].get("reply_fallback", False),
                        "rejected": result["audit"].get("rejected_candidates", []),
                    },
                    ensure_ascii=False,
                )
            )


def receipts_summary(out):
    totals = defaultdict(lambda: defaultdict(int))
    elapsed = defaultdict(list)
    for path in sorted(out.glob("**/*-receipt.json")):
        result = read(path)
        parts = path.relative_to(out).parts
        key = "/".join((parts[0], parts[1], result["stage"]))
        total = totals[key]
        total["calls"] += 1
        elapsed[key].append(result["seconds"])
        if result.get("error") or result.get("failed"):
            total["failures"] += 1
        response = result.get("response", {})
        usage = response.get("usage", {})
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            total[name] += usage.get(name, 0)
        total["usage_available"] += bool(usage)
        total["length_finishes"] += any(
            c.get("finish_reason") == "length" for c in response.get("choices", [])
        )
    summary = {}
    for key, total in totals.items():
        durations = sorted(elapsed[key])
        summary[key] = {
            **dict(total),
            "p50_seconds": round(median(durations), 2),
            "p95_seconds": round(durations[ceil(len(durations) * 0.95) - 1], 2),
            "max_seconds": round(max(durations), 2),
        }
    return summary


def score(out, review):
    cases = {c["id"]: c for c in CASES}
    totals = defaultdict(lambda: defaultdict(int))
    details = []
    for path in sorted((out / "recording").glob("*/*/result.json")):
        result = read(path)
        case = cases[result["case"]]
        key = f"{result['group']}/{result['case']}"
        decision = review[key]
        rows = saved_atoms(result)
        matches = {int(i): j for i, j in decision["matches"].items()}
        extras = set(decision.get("supported_extras", []))
        evidence = set(decision["evidence_supported"])
        composites = {
            int(j): indices for j, indices in decision.get("composite_matches", {}).items()
        }
        if (
            set(matches) != set(range(len(rows)))
            or not extras <= set(matches)
            or not evidence <= set(matches)
            or any(matches[i] is not None for i in extras)
        ):
            raise ValueError(f"invalid_review_indices:{key}")
        if any(
            j is not None and (type(j) is not int or not 0 <= j < len(case["targets"]))
            for j in matches.values()
        ):
            raise ValueError(f"invalid_target_index:{key}")
        targets = {j for j in matches.values() if j is not None}
        if any(
            not 0 <= j < len(case["targets"])
            or len(indices) < 2
            or not set(indices) <= set(matches)
            for j, indices in composites.items()
        ):
            raise ValueError(f"invalid_composite_match:{key}")
        targets |= set(composites)
        supported = {i for i, j in matches.items() if j is not None} | extras
        fields = {
            j
            for i, j in matches.items()
            if j is not None and rows[i]["field"] == case["targets"][j]["field"]
        }
        fields |= {
            j
            for j, indices in composites.items()
            if all(rows[i]["field"] == case["targets"][j]["field"] for i in indices)
        }
        total = totals[result["group"]]
        total["cases"] += 1
        total["completed"] += result["audit"]["verdict"] == "pass"
        total["gold"] += len(case["targets"])
        total["recovered"] += len(targets)
        total["field_recovered"] += len(fields)
        total["saved"] += len(rows)
        total["supported"] += len(supported)
        total["evidence_complete"] += len(evidence & supported)
        total["bad_questions"] += bool(decision.get("question_issues"))
        total["reply_fallbacks"] += bool(result["audit"].get("reply_fallback"))
        total["boundary_failures"] += not decision.get("boundary_pass", True)
        details.append(
            {
                "id": key,
                "recovered": len(targets),
                "gold": len(case["targets"]),
                "saved": len(rows),
                "supported": len(supported),
                "evidence_complete": len(evidence & supported),
                "question_issues": decision.get("question_issues", []),
            }
        )
    scores = {}
    for group, total in totals.items():
        value = dict(total)
        for metric, numerator, denominator in (
            ("recall", "recovered", "gold"),
            ("precision", "supported", "saved"),
            ("field_recall", "field_recovered", "gold"),
            ("evidence_completeness", "evidence_complete", "saved"),
            ("completion_rate", "completed", "cases"),
        ):
            value[metric] = (
                round(total[numerator] / total[denominator] * 100, 2)
                if total[denominator]
                else None
            )
        scores[group] = value
    return {
        "scope": "single-round targeted recording pilot; not full acceptance",
        "reviewer": "same coding assistant; no independent human blind review",
        "scores": scores,
        "details": details,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--review", type=Path)
    parser.add_argument("--interview", action="store_true")
    parser.add_argument("--receipts", action="store_true")
    parser.add_argument("--groups", nargs="*")
    parser.add_argument("--turns", type=int, nargs="*")
    args = parser.parse_args()
    if args.receipts:
        print(json.dumps(receipts_summary(args.out), ensure_ascii=False, indent=2))
    elif args.interview:
        inspect_interviews(args.out, args.groups, args.turns)
    elif args.review:
        result = score(args.out, read(args.review))
        (args.out / "reviewed-recording-scores.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result["scores"], ensure_ascii=False))
    else:
        inspect(args.out, args.cases)


if __name__ == "__main__":
    main()

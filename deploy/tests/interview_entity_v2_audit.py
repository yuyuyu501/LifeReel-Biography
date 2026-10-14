"""Display or apply explicit semantic reviews for the v2 experiment; no API calls."""

import argparse
import hashlib
import json
from pathlib import Path

from interview_entity_v2 import GROUPS, dump, score


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def show(out, limit):
    cases = read(out / "frozen-cases.json")
    decisions = read(out / "semantic-decisions.json")
    reviewed = {tuple(x) for x in decisions["reviewed_case_rounds"]}
    displayed = 0
    for repeat in (1, 2):
        for item in cases:
            if (item["id"], repeat) in reviewed:
                continue
            paths = [out / f"r{repeat}/{g}/{item['id']}/result.json" for g in GROUPS]
            if not all(p.exists() for p in paths):
                continue
            catalog = []

            def refs(evidence, catalog=catalog):
                indices = []
                for e in evidence:
                    pair = [e["source_id"], e["quote"]]
                    if pair not in catalog:
                        catalog.append(pair)
                    indices.append(catalog.index(pair))
                return indices

            variants = {}
            for path in paths:
                result = read(path)
                metric = score(result, item)
                view = {
                    "status": result["status"],
                    "rows": [
                        [
                            i,
                            metric["matches"][i],
                            f["subject"],
                            f["predicate"],
                            f["value"],
                            f["status"],
                            f["fields"],
                            refs(f["evidence"]),
                        ]
                        for i, f in enumerate(result.get("output", {}).get("facts", []))
                    ],
                    "pending": [
                        [
                            p.get("reason"),
                            p.get("question"),
                            p.get("entity_candidates"),
                            refs(p["evidence"]),
                        ]
                        for p in result.get("output", {}).get("abstentions", [])
                    ],
                    "rejected": [
                        [
                            i,
                            r["candidate"]["entity_id"],
                            r["candidate"]["predicate"],
                            r["candidate"]["value"],
                            r["candidate"]["status"],
                            r["reason"],
                            refs(r["candidate"]["evidence"]),
                        ]
                        for i, r in enumerate(result.get("rejected", []))
                    ],
                }
                key = json.dumps(view, ensure_ascii=False, sort_keys=True)
                variants.setdefault(key, []).append(path.relative_to(out).parent.as_posix())
            print(
                json.dumps(
                    {
                        "case": item["id"],
                        "repeat": repeat,
                        "target": item["sources"][-1],
                        "gold": [
                            [g["subject"], g["predicate"], g["value"], g["status"], g["sources"]]
                            for g in item["gold"]
                        ],
                        "quotes": catalog,
                    },
                    ensure_ascii=False,
                )
            )
            for key, ids in variants.items():
                print(json.dumps({"ids": ids, "view": json.loads(key)}, ensure_ascii=False))
            displayed += 1
            if displayed >= limit:
                return


def apply(out):
    cases = {c["id"]: c for c in read(out / "frozen-cases.json")}
    decisions = read(out / "semantic-decisions.json")
    reviewed = decisions["reviewed_case_rounds"]
    if len(reviewed) != len({tuple(r) for r in reviewed}):
        raise ValueError("duplicate_reviewed_case_round")
    audits = {}
    for case, repeat in reviewed:
        if repeat not in (1, 2) or case not in cases:
            raise ValueError("invalid_reviewed_case_round")
        item = cases[case]
        for group in GROUPS:
            identifier = f"r{repeat}/{group}/{case}"
            path = out / identifier / "result.json"
            result = read(path)
            metrics = score(result, item)
            changes = decisions["overrides"].get(identifier, {})
            pairs = {str(i): j for i, j in metrics["matches"].items()}
            pairs.update(changes.get("pairs", {}))
            rows = result.get("output", {}).get("facts", [])
            invalid = changes.get("invalid_evidence", [])
            rejected = changes.get("rejected_supported", [])
            if not set(invalid) <= set(range(len(rows))) or not set(rejected) <= set(
                range(len(result.get("rejected", [])))
            ):
                raise ValueError("invalid_review_indices")
            audit = {
                "pairs": pairs,
                "supported_extras": changes.get("supported_extras", []),
                "evidence_supported": [i for i in range(len(rows)) if i not in invalid],
                "rejected_supported": rejected,
                "notes": changes.get(
                    "notes",
                    "Final and rejected candidates inspected by Codex; "
                    "no independent human annotation.",
                ),
                "result_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            if item["requires_pending"]:
                if "pending_safe" not in changes:
                    raise ValueError(f"missing_explicit_ambiguity_review:{identifier}")
                audit["pending_safe"] = changes["pending_safe"]
            score(result, item, audit)
            audits[identifier] = audit
    if not decisions["overrides"].keys() <= audits.keys():
        raise ValueError("override_for_unreviewed_result")
    dump(out / "manual-audit.json", audits)
    print(f"Recorded {len(audits)} explicitly reviewed results.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args()
    if args.apply:
        apply(args.out)
    else:
        show(args.out, args.limit)


if __name__ == "__main__":
    main()

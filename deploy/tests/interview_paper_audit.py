"""Display all receipts for manual semantic review; never calls a provider."""

import argparse
import json
from pathlib import Path

from interview_paper_methods import dump, evidence_valid, score


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--groups", nargs="+", default=["A0", "A1", "A2", "A3", "A4"])
    parser.add_argument("--review", type=Path)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--inherit-from", type=Path)
    args = parser.parse_args()
    cases = read(args.out / "frozen-cases.json")
    manual = read(args.review) if args.review else None
    reviews = (
        read(args.out / "manual-audit.json") if (args.out / "manual-audit.json").exists() else {}
    )
    prior_reviews = {}
    if args.inherit_from:
        prior_reviews = read(args.inherit_from / "manual-audit.json")
        if read(args.inherit_from / "frozen-cases.json") != cases:
            raise ValueError("different_frozen_cases")
        current_manifest = read(args.out / "manifest.json")
        prior_manifest = read(args.inherit_from / "manifest.json")
        for key in ("fingerprint", "model", "temperature", "max_output_tokens"):
            if current_manifest[key] != prior_manifest[key]:
                raise ValueError("different_frozen_implementation")
    inherited = 0
    for group in args.groups:
        for item in cases:
            identifier = f"r{args.repeat}/{group}/{item['id']}"
            path = args.out / identifier / "result.json"
            if not path.exists():
                continue
            result = read(path)
            if args.inherit_from:
                previous_path = args.inherit_from / identifier / "result.json"
                previous = read(previous_path) if previous_path.exists() else None
                if (
                    previous
                    and previous["status"] == result["status"]
                    and previous.get("output") == result.get("output")
                    and identifier in prior_reviews
                ):
                    reviews[identifier] = {
                        **prior_reviews[identifier],
                        "notes": "Reused audit: identical output and frozen input.",
                    }
                    inherited += 1
                    continue
            metric = score(result, item)
            rows = result.get("output", {}).get("facts", [])
            if manual:
                if identifier not in manual["reviewed"]:
                    continue
                edits = manual.get("overrides", {}).get(identifier, {})
                pairs = {str(i): j for i, j in metric["matches"].items()}
                pairs.update(edits.get("pairs", {}))
                invalid = set(edits.get("invalid_evidence", []))
                reviews[identifier] = {
                    "pairs": pairs,
                    "supported_extras": edits.get("supported_extras", []),
                    "evidence_supported": [i for i in range(len(rows)) if i not in invalid],
                    "reviewer": "Codex semantic audit; no independent human annotation",
                    "notes": edits.get("notes", "All predictions and missing gold inspected."),
                }
            else:
                data = {
                    "id": identifier,
                    "status": result["status"],
                    "missing": metric["missing"],
                    "abstentions": result.get("output", {}).get("abstentions", []),
                    "rows": [],
                }
                for i, row in enumerate(rows):
                    data["rows"].append(
                        {
                            "i": i,
                            "gold": metric["matches"][i],
                            "fact": [
                                row.get(k) for k in ("subject", "predicate", "value", "status")
                            ],
                            "fields": row.get("fields"),
                            "evidence": row.get("evidence"),
                            "exact_quote": evidence_valid(row.get("evidence", []), item["sources"]),
                        }
                    )
                print(json.dumps(data, ensure_ascii=False))
    if manual:
        dump(args.out / "manual-audit.json", reviews)
        print(f"Recorded {len(reviews)} explicit reviews.")
    elif args.inherit_from:
        dump(args.out / "manual-audit.json", reviews)
        print(f"Inherited {inherited} identical-output reviews; other outputs listed above.")


if __name__ == "__main__":
    main()

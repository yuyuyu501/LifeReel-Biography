"""Offline explicit semantic audit application; never uses a provider."""

import argparse
import json
from pathlib import Path

from interview_entity_methods import GROUPS
from interview_paper_methods import dump, score


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    cases = json.loads((args.out / "frozen-cases.json").read_text(encoding="utf-8"))
    repeats = json.loads((args.out / "manifest.json").read_text(encoding="utf-8"))["repeats"]
    manual = json.loads(args.review.read_text(encoding="utf-8")) if args.review else None
    audits = {}
    for repeat in range(1, repeats + 1):
        for item in cases:
            for group in GROUPS:
                identifier = f"r{repeat}/{group}/{item['id']}"
                path = args.out / identifier / "result.json"
                if not path.exists():
                    continue
                result = json.loads(path.read_text(encoding="utf-8"))
                metrics = score(result, item)
                rows = result.get("output", {}).get("facts", [])
                if manual:
                    if identifier not in manual["reviewed"]:
                        continue
                    changes = manual.get("overrides", {}).get(identifier, {})
                    pairs = {str(i): j for i, j in metrics["matches"].items()}
                    pairs.update(changes.get("pairs", {}))
                    audits[identifier] = {
                        "pairs": pairs,
                        "supported_extras": changes.get("supported_extras", []),
                        "evidence_supported": [
                            i
                            for i in range(len(rows))
                            if i not in changes.get("invalid_evidence", [])
                        ],
                        "reviewer": "Codex semantic audit; no independent human annotation",
                        "notes": changes.get(
                            "notes", "All final and rejected candidates inspected."
                        ),
                        "rejected_supported": changes.get("rejected_supported", []),
                    }
                    if item["requires_pending"]:
                        if "pending_safe" not in changes:
                            raise ValueError(f"missing_explicit_ambiguity_review:{identifier}")
                        audits[identifier]["pending_safe"] = changes["pending_safe"]
                    score(result, item, audits[identifier])
                else:
                    print(
                        json.dumps(
                            {
                                "id": identifier,
                                "status": result["status"],
                                "rows": [
                                    {"i": i, "gold": metrics["matches"][i], **r}
                                    for i, r in enumerate(rows)
                                ],
                                "missing": metrics["missing"],
                                "pending": result.get("output", {}).get("abstentions", []),
                                "rejected": result.get("rejected", []),
                            },
                            ensure_ascii=False,
                        )
                    )
    if manual:
        dump(args.out / "manual-audit.json", audits)
        print(f"Recorded {len(audits)} explicit semantic audits.")


if __name__ == "__main__":
    main()

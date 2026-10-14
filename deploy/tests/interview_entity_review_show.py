"""Show completed, unreviewed case rounds with shared quote catalogs; no provider calls."""

import argparse
import json
from pathlib import Path

from interview_entity_methods import GROUPS
from interview_paper_methods import score


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()
    cases = read(args.out / "frozen-cases.json")
    repeats = read(args.out / "manifest.json")["repeats"]
    decisions = read(args.out / "semantic-decisions.json")
    reviewed = {tuple(x) for x in decisions["reviewed_case_rounds"]}
    displayed = 0
    for repeat in range(1, repeats + 1):
        for item in cases:
            if (item["id"], repeat) in reviewed:
                continue
            paths = [args.out / f"r{repeat}/{group}/{item['id']}/result.json" for group in GROUPS]
            if not all(p.exists() for p in paths):
                continue
            catalog = []

            def refs(evidence, catalog=catalog):
                indices = []
                for excerpt in evidence:
                    pair = [excerpt["source_id"], excerpt["quote"]]
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
                            x["candidate"]["entity_id"],
                            x["candidate"]["predicate"],
                            x["candidate"]["value"],
                            x["candidate"]["status"],
                            x["reason"],
                            refs(x["candidate"]["evidence"]),
                        ]
                        for i, x in enumerate(result.get("rejected", []))
                    ],
                }
                key = json.dumps(view, ensure_ascii=False, sort_keys=True)
                variants.setdefault(key, []).append(path.relative_to(args.out).parent.as_posix())
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
            if displayed >= args.limit:
                return


if __name__ == "__main__":
    main()

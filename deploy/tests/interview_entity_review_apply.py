"""Expand explicit reviewed case/round decisions, without inferring audit decisions."""

import argparse
import json
from pathlib import Path

from interview_entity_methods import GROUPS
from interview_paper_methods import dump


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    decisions = json.loads((args.out / "semantic-decisions.json").read_text(encoding="utf-8"))
    reviewed = []
    hashes = {}
    import hashlib

    for case, repeat in decisions["reviewed_case_rounds"]:
        for group in GROUPS:
            identifier = f"r{repeat}/{group}/{case}"
            path = args.out / identifier / "result.json"
            if not path.exists():
                raise ValueError(f"missing_reviewed_result:{identifier}")
            reviewed.append(identifier)
            hashes[identifier] = hashlib.sha256(path.read_bytes()).hexdigest()
    if len(reviewed) != len(set(reviewed)):
        raise ValueError("duplicate_reviewed_case_round")
    if not decisions["overrides"].keys() <= set(reviewed):
        raise ValueError("override_for_unreviewed_result")
    dump(
        args.out / "semantic-review.json",
        {
            "reviewed": reviewed,
            "overrides": decisions["overrides"],
            "result_hashes": hashes,
            "reviewer": "Codex semantic audit; no independent human annotation",
        },
    )
    print(f"Expanded {len(reviewed)} explicitly reviewed results.")


if __name__ == "__main__":
    main()

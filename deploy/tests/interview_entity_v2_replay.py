"""Post-hoc metadata scope fix; reuses frozen outputs without new provider calls."""

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from interview_entity_v2 import GROUPS, ROOT, apply_v2, dump, summarize

REPLAY_VERSION = "entity-v2-metadata-scope-replay-v1"
RECORD_METADATA = {"material_status", "deferred_topic"}


def recover_metadata(result, sources):
    output = deepcopy(result)
    output["posthoc_changes"] = []
    if result["status"] != "ok":
        return output
    rejected = []
    for rejection in result.get("rejected", []):
        row = rejection["candidate"]
        # These predicates describe the session's material backlog, not a person's identity.
        recoverable = (
            rejection["reason"] == "missing_entity_anchor"
            and row["entity_id"] == "self"
            and row["entity_candidates"] == ["self"]
            and row["predicate"] in RECORD_METADATA
        )
        if not recoverable:
            rejected.append(rejection)
            continue
        scoped = {**row, "resolution": "explicit"}
        recovered, still_rejected, _ = apply_v2({"candidates": [scoped], "pending": []}, sources)
        if still_rejected:
            rejected.append(rejection)
            continue
        output["output"]["facts"].extend(recovered["facts"])
        output["output"]["abstentions"] = [
            p
            for p in output["output"]["abstentions"]
            if p.get("candidate_id") != row["candidate_id"]
        ]
        output["posthoc_changes"].append(
            {
                "candidate_id": row["candidate_id"],
                "action": "use_session_metadata_scope",
                "original_resolution": row["resolution"],
            }
        )
    output["rejected"] = rejected
    return output


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def replay(source, out):
    if source.resolve() == out.resolve():
        raise ValueError("cannot_overwrite_live_experiment")
    manifest = read(source / "manifest.json")
    cases = read(source / "frozen-cases.json")
    results = []
    for repeat in (1, 2):
        for item in cases:
            for group in GROUPS:
                identifier = f"r{repeat}/{group}/{item['id']}"
                path = source / identifier / "result.json"
                if not path.exists():
                    raise ValueError("live_results_incomplete")
                result = recover_metadata(read(path), item["sources"])
                result["parent_result_hash"] = hashlib.sha256(path.read_bytes()).hexdigest()
                results.append((identifier, result))
    files = [Path(__file__), Path(__file__).with_name("test_interview_entity_v2_replay.py")]
    replay_manifest = {
        **manifest,
        "version": REPLAY_VERSION,
        "fingerprint": {
            **manifest["fingerprint"],
            **{
                p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in files
            },
        },
        "scope": "post-hoc offline replay, not a new live test or product acceptance",
        "parent": str(source.resolve()),
        "max_calls": 0,
    }
    if out.exists():
        raise ValueError("replay_output_already_exists")
    out.mkdir(parents=True)
    dump(out / "manifest.json", replay_manifest)
    dump(out / "frozen-cases.json", cases)
    parent_decisions = read(source / "semantic-decisions.json")
    changed_rounds = {(r["case"], r["repeat"]) for _, r in results if r["posthoc_changes"]}
    decisions = {
        "reviewed_case_rounds": [
            r for r in parent_decisions["reviewed_case_rounds"] if tuple(r) not in changed_rounds
        ],
        "overrides": {},
        "inherited_review": (
            "Unchanged facts inherit the explicit parent review; "
            "changed case rounds require fresh review."
        ),
    }
    for identifier, changes in parent_decisions["overrides"].items():
        repeat, _, case = identifier.split("/")
        if (case, int(repeat[1:])) not in changed_rounds:
            decisions["overrides"][identifier] = changes
    dump(out / "semantic-decisions.json", decisions)
    for name in replay_manifest["fingerprint"]:
        path = out / "executed-source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
    for identifier, result in results:
        path = out / identifier / "result.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        dump(path, result)
    print(
        json.dumps(
            {"results": len(results), "changed_rounds": sorted(changed_rounds), "provider_calls": 0}
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summarize", action="store_true")
    args = parser.parse_args()
    if args.summarize:
        summarize(args.out)
    elif args.source:
        replay(args.source, args.out)
    else:
        parser.error("--source is required for replay")


if __name__ == "__main__":
    main()

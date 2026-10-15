"""Replay cached verification responses with network disabled; no new live scores."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import httpx
from interview_grounding_experiment import ROOT, dump
from interview_grounding_replay import read, replay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source, out = args.source.resolve(), args.out.resolve()
    if not all(p.is_relative_to(ROOT / "tmp") for p in (source, out)) or out.exists():
        raise ValueError("use_new_ignored_output_directory")
    spec = importlib.util.spec_from_file_location("replay_isolated",
                                               ROOT / "apps/api/tests/conftest.py")
    isolated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated)
    from lifereel_api.core.config import get_settings
    from lifereel_api.modules.interview import d4

    try:
        settings = get_settings()
        settings.openai_compatible_base_url = "https://synthetic.invalid/v1"
        settings.openai_compatible_api_key = "synthetic"
        settings.interview_llm_backend = "inherit"
        settings.interview_llm_model = "lite-replay"
        settings.interview_review_llm_model = "sol-replay"
        settings.interview_review_enabled = True
        settings.interview_history_enabled = False
        results, skipped = {}, []
        with patch.object(httpx, "post", side_effect=RuntimeError("offline_network_forbidden")):
            for path in sorted(source.glob("recording/*/*/turn-*/result.json")):
                directory = path.parent
                key = directory.relative_to(source).as_posix()
                if not all((directory / f"{stage}-receipt.json").exists()
                           and "response" in read(directory / f"{stage}-receipt.json")
                           for stage in ("lite", "sol")):
                    skipped.append(key)
                    continue
                mode = path.relative_to(source).parts[1]
                result = replay(directory, mode)
                results[key] = result
                print(json.dumps({"id": key, "original": result["original_verdict"],
                    "replay": result["audit"]["verdict"],
                    "conflicts": result["audit"].get("conflict_indices"),
                    "rejected": result["audit"].get("rejected_candidates"),
                    "fields": [c["field_key"] for c in result["output"]["changes"]]},
                    ensure_ascii=False), flush=True)
        dump(out / "result.json", {"kind": "offline_cached_response_replay", "live_calls": 0,
             "source": str(source), "runtime_version": d4.VERSION,
             "runtime_hashes": {
                 p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
                     "services/interview/src/lifereel_api/modules/interview/d4.py",
                     "services/interview/src/lifereel_api/modules/interview/grounding.py",
                 )
             },
             "cases": results, "transport_failures_not_replayed": skipped})
    finally:
        isolated.pytest_sessionfinish()


if __name__ == "__main__":
    main()

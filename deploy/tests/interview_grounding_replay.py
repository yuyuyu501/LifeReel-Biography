"""Offline protocol regression using unchanged paid responses; never new live scores."""

import argparse
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def replay(directory, mode):
    from lifereel_api.modules.interview import d4
    from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

    messages = read(directory / "lite-request.json")["payload"]["messages"]
    material = json.loads(next(m["content"] for m in messages if m["role"] == "user"))
    cached = {}
    for stage in ("lite", "sol"):
        response = read(directory / f"{stage}-receipt.json")["response"]
        cached[stage] = json.loads(response["choices"][0]["message"]["content"])
    calls = []

    def structured(self, system, user, schema, **kwargs):
        stage = "lite" if self.model == "lite-replay" else "sol"
        calls.append(stage)
        return deepcopy(cached[stage])

    with (
        patch.object(OpenAICompatibleClient, "chat_structured", structured),
        patch.object(httpx.Client, "send", side_effect=RuntimeError("offline_network_forbidden")),
    ):
        output, audit = d4.generate(OpenAICompatibleClient.for_task("interview"), material,
                                    enhancement=mode)
    assert calls == ["lite", "sol"]
    original = read(directory / "result.json")
    original_audit = original.get("audit", original.get("result", {}).get("audit", {}))
    return {
        "original_verdict": original_audit.get("verdict"),
        "output": output,
        "audit": audit,
        "cached_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.glob("*-receipt.json")
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source, out = args.source.resolve(), args.out.resolve()
    if not source.is_relative_to(ROOT / "tmp") or not out.is_relative_to(ROOT / "tmp"):
        raise ValueError("receipts_and_replay_must_stay_in_ignored_tmp")
    if out.exists():
        raise FileExistsError("preserve_previous_replay_use_new_output")
    spec = importlib.util.spec_from_file_location(
        "replay_isolated", ROOT / "apps/api/tests/conftest.py"
    )
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
        cases = {
            f"{mode}/G08": replay(source / "recording" / mode / "G08", mode)
            for mode in ("baseline", "reasoning", "retrieval", "combined")
        }
        cases["reasoning/interview-03"] = replay(
            source / "interview/reasoning/turn-03", "reasoning"
        )
        result = {
            "kind": "unchanged-provider-response-offline-replay",
            "live_calls": 0,
            "source": str(source),
            "runtime_version": d4.VERSION,
            "d4_sha256": hashlib.sha256(Path(d4.__file__).read_bytes()).hexdigest(),
            "cases": cases,
        }
        out.mkdir(parents=True)
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
        print(json.dumps({key: {
            "original": value["original_verdict"], "replay": value["audit"]["verdict"],
            "fields": [c["field_key"] for c in value["output"]["changes"]],
            "next_question": value["output"]["next_question"],
        } for key, value in cases.items()}, ensure_ascii=False))
    finally:
        isolated.pytest_sessionfinish()


if __name__ == "__main__":
    main()

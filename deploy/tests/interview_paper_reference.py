"""Run the unchanged app fact inventory on the already frozen synthetic cases."""

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import dotenv_values
from interview_paper_methods import MODEL, ROOT, call, dump

from lifereel_api.modules.interview import quality


def run(item, credentials, out):
    directory = out / item["id"]
    if (directory / "result.json").exists():
        return json.loads((directory / "result.json").read_text(encoding="utf-8"))
    directory.mkdir(parents=True, exist_ok=True)
    endpoint, key = credentials

    class Adapter:
        def chat_json(self, system, data):
            return call(endpoint, key, MODEL, "inventory", system, json.loads(data), directory)

    current = item["sources"][-1]
    material = {
        "new_answer": current["text"],
        "source_ids": [f"turn:{current['id']}:v1"],
        "recent_dialogue": [
            {"id": f"turn:{r['id']}:v1", "answer": r["text"]} for r in item["sources"][:-1]
        ],
        "current_entries": [],
    }
    result = {"case": item["id"], "category": item["category"]}
    start = time.perf_counter()
    try:
        result.update(status="ok", facts=quality.inventory(Adapter(), material))
    except (ValueError, TypeError, KeyError, RuntimeError) as exc:
        result.update(status="failed", error=type(exc).__name__)
    result["seconds"] = round(time.perf_counter() - start, 3)
    dump(directory / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cases = json.loads((args.experiment / "frozen-cases.json").read_text(encoding="utf-8"))
    prompt_hash = hashlib.sha256(quality.INVENTORY_PROMPT.encode()).hexdigest()
    dump(
        args.out / "manifest.json",
        {
            "model": MODEL,
            "inventory_prompt_sha256": prompt_hash,
            "source_experiment": str(args.experiment),
            "temperature": 0,
            "scope": "Unchanged inventory function; not full app pipeline",
        },
    )
    env = dotenv_values(ROOT / ".env")
    credentials = env.get("VOLCENGINE_API_BASE_URL"), env.get("VOLCENGINE_API_KEY")
    if not all(credentials):
        raise SystemExit("LITE_CREDENTIAL_MISSING")
    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(run, c, credentials, args.out) for c in cases]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps({k: result[k] for k in ("case", "status", "seconds")}), flush=True)
    dump(args.out / "results.json", sorted(results, key=lambda r: r["case"]))


if __name__ == "__main__":
    main()

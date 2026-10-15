"""Opt-in four-way D4 experiment; private receipts stay in ignored tmp."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from dotenv import dotenv_values
from interview_grounding_cases import CASES, PERSONA

ROOT = Path(__file__).resolve().parents[2]
GROUPS = ("baseline", "reasoning", "retrieval", "combined")
CALL_DIRECTORY = ContextVar("call_directory", default=None)
FILES = [
    "services/interview/src/lifereel_api/modules/interview/d4.py",
    "services/interview/src/lifereel_api/modules/interview/grounding.py",
    "services/interview/src/lifereel_api/modules/interview/retrieval.py",
    "services/interview/src/lifereel_api/modules/interview/quality.py",
    "services/interview/src/lifereel_api/modules/interview/profile_extraction.py",
    "deploy/tests/interview_grounding_cases.py",
    "deploy/tests/interview_grounding_experiment.py",
]


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def bootstrap():
    if "lifereel_api.core.database" in sys.modules:
        raise RuntimeError("isolation_must_be_initialized_before_application_imports")
    private = dotenv_values(ROOT / ".env")
    spec = importlib.util.spec_from_file_location(
        "isolated_settings", ROOT / "apps/api/tests/conftest.py"
    )
    isolated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated)
    from lifereel_api.core.config import get_settings
    from lifereel_api.core.database import engine

    if Path(engine.url.database).resolve() != isolated.TEST_DB.resolve():
        raise RuntimeError("experiment_database_is_not_isolated")

    settings = get_settings()
    for key in (
        "openai_compatible_base_url",
        "openai_compatible_api_key",
        "volcengine_api_key",
        "volcengine_api_base_url",
    ):
        if private.get(key.upper()):
            setattr(settings, key, private[key.upper()])
    settings.llm_provider = "openai-compatible"
    settings.interview_enhancements_enabled = True
    settings.interview_recording_method = "d4"
    settings.interview_review_enabled = True
    settings.interview_history_enabled = False
    settings.interview_sync_assistance_enabled = False
    settings.interview_llm_backend = "volcengine"
    settings.interview_llm_model = "doubao-seed-2-1-lite-260915"
    settings.interview_review_llm_model = "gpt-6.1-sol"
    settings.interview_llm_thinking = "disabled"
    settings.interview_llm_read_timeout_seconds = 90
    settings.interview_review_llm_read_timeout_seconds = 240
    settings.interview_review_llm_connect_timeout_seconds = 20
    settings.interview_turn_budget_seconds = 300
    settings.llm_min_interval_seconds = 0
    settings.llm_stream = False
    settings.interview_d4_enhancement = "baseline"
    return settings, isolated


def recording_material(case):
    answers = case["answers"]
    rows = [
        {
            "id": f"round:U{i}:v1",
            "record_id": f"U{i}",
            "version": 1,
            "answer": answer,
            "question": "请接着讲。",
        }
        for i, answer in enumerate(answers[:-1], 1)
    ]
    sid = f"current:U{len(answers)}:v1"
    material = {
        "new_answer": answers[-1],
        "source_ids": [sid, *[r["id"] for r in rows[-8:]]],
        "current_source": {"type": "test", "id": f"U{len(answers)}", "version": 1},
        "current_entries": [],
        "entry_index": [],
        "recent_dialogue": rows[-8:],
        "recent_questions": [],
        "pending_fact_records": [],
        "state": {},
        "readiness": {"status": "insufficient", "missing_fields": [], "scope": "整个人生"},
        "interview_policy": {},
        "strategy_advice": None,
    }
    return material, rows


def receipt_transport():
    original = httpx.post

    def post(url, **kwargs):
        directory = CALL_DIRECTORY.get()
        if directory is None:
            return original(url, **kwargs)
        payload = kwargs.get("json", {})
        stage = "lite" if payload.get("model", "").startswith("doubao") else "sol"
        request = {"stage": stage, "payload": payload}
        # Authorization headers and endpoint credentials are deliberately omitted.
        dump(directory / f"{stage}-request.json", request)
        result = {"stage": stage, "requested_model": payload.get("model")}
        start = time.monotonic()
        try:
            response = original(url, **kwargs)
            result["http_status"] = response.status_code
            if response.is_success:
                result["response"] = response.json()
            else:
                result["failed"] = True
            return response
        except httpx.HTTPError as exc:
            result["error"] = type(exc).__name__
            raise
        finally:
            result["seconds"] = round(time.monotonic() - start, 3)
            dump(directory / f"{stage}-receipt.json", result)

    httpx.post = post


def run_case(case, mode, out):
    from lifereel_api.modules.interview import d4, retrieval
    from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

    directory = out / "recording" / mode / case["id"]
    path = directory / "result.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    # A request without a result may have consumed a paid invocation; never silently retry it.
    if (directory / "lite-request.json").exists():
        raise RuntimeError("unfinished_paid_case_requires_inspection")
    material, rows = recording_material(case)
    if mode in {"retrieval", "combined"}:
        material = retrieval.enrich_material(material, [], rows)
    token = CALL_DIRECTORY.set(directory)
    try:
        output, audit = d4.generate(
            OpenAICompatibleClient.for_task("interview"), material, enhancement=mode
        )
        result = {
            "case": case["id"],
            "group": mode,
            "output": output,
            "audit": audit,
            "selected_sources": material.get("retrieved_sources", []),
        }
        dump(path, result)
        return result
    finally:
        CALL_DIRECTORY.reset(token)


def choose_answer(question, counts):
    options = []
    for topic in PERSONA["topics"]:
        score = sum(cue in question for cue in topic["cues"])
        index = counts.get(topic["id"], 0)
        if score and index < len(topic["answers"]):
            options.append((score, -index, topic, index))
    if not options:
        return "这个细节我记不清了。", "unknown"
    _, _, topic, index = max(options, key=lambda x: (x[0], x[1]))
    counts[topic["id"]] = index + 1
    return topic["answers"][index], topic["id"]


def interview(mode, out, turns):
    from fastapi.testclient import TestClient

    from lifereel_api.core.config import get_settings
    from lifereel_api.core.database import Base, SessionLocal, engine
    from lifereel_api.core.errors import ApiError
    from lifereel_api.main import app
    from lifereel_api.modules.interview import profile_service
    from lifereel_api.modules.interview.models import InterviewRound, InterviewTurnWorkflow
    from lifereel_api.modules.interview.profile_extraction import process

    directory = out / "interview" / mode
    if (directory / "result.json").exists():
        return
    if directory.exists() and list(directory.glob("turn-*/lite-request.json")):
        raise RuntimeError("unfinished_interview_requires_inspection")
    settings = get_settings()
    settings.interview_d4_enhancement = mode
    results, counts = [], {}
    consecutive_failures = 0
    with TestClient(app) as client:
        person_response = client.post("/v1/persons", json={"display_name": "检索对照合成人物"})
        person_response.raise_for_status()
        session_response = client.post(
            "/v1/interviews", json={"subject_id": person_response.json()["id"]}
        )
        session_response.raise_for_status()
        session = session_response.json()
        question = "您愿意先讲哪段经历？"
        for turn in range(1, turns + 1):
            initiated = turn in {1, turns - 3, turns - 2, turns - 1, turns}
            if turn == 1:
                answer, topic = PERSONA["opening"], "opening"
            elif turn == turns - 3:
                answer, topic = PERSONA["boundary_answer"], "privacy_probe"
            elif turn == turns - 2:
                answer, topic = PERSONA["resume_answer"], "resume_probe"
            elif turn == turns - 1:
                answer, topic = PERSONA["correction_answer"], "correction_probe"
            elif turn == turns:
                answer, topic = PERSONA["close_answer"], "close_probe"
            else:
                answer, topic = choose_answer(question, counts)
            turn_dir = directory / f"turn-{turn:02d}"
            token = CALL_DIRECTORY.set(turn_dir)
            try:
                with SessionLocal() as db:
                    row = InterviewRound(
                        tenant_id=settings.default_tenant_id,
                        session_id=UUID(session["id"]),
                        round_index=turn + 1,
                        question_text=question,
                        answer_text=answer,
                        answer_version=1,
                    )
                    db.add(row)
                    db.commit()
                    request_id = uuid4()
                    workflow = InterviewTurnWorkflow(
                        tenant_id=settings.default_tenant_id,
                        session_id=UUID(session["id"]),
                        round_id=row.id,
                        idempotency_key=str(request_id),
                        status="running",
                        profile_result={},
                    )
                    db.add(workflow)
                    db.commit()
                    try:
                        result = process(
                            db,
                            settings.default_tenant_id,
                            UUID(session["profile_id"]),
                            answer,
                            {"type": "interview_round", "id": str(row.id), "version": 1},
                            request_id,
                            workflow=workflow,
                        )
                        workflow.status = "completed"
                    except ApiError as exc:
                        result = {
                            "profile": profile_service.read(
                                db, settings.default_tenant_id, UUID(session["profile_id"])
                            ),
                            "audit": workflow.profile_result.get("audit", {}),
                            "next_question": "这轮记录尚未完成，请稍后核对。",
                            "error": exc.code.value,
                        }
                        workflow.status = "failed"
                    db.commit()
                record = {
                    "turn": turn,
                    "question": question,
                    "answer": answer,
                    "topic": topic,
                    "tester_initiated": initiated,
                    "result": result,
                }
                results.append(record)
                dump(turn_dir / "result.json", record)
                question = result["next_question"]
                print(
                    json.dumps(
                        {
                            "track": "interview",
                            "group": mode,
                            "turn": turn,
                            "verdict": result["audit"].get("verdict"),
                            "topic": topic,
                        },
                        ensure_ascii=True,
                    ),
                    flush=True,
                )
                # Refresh via the normal profile endpoint before the next independent transaction.
                refreshed = client.get(f"/v1/life-profiles/{session['profile_id']}")
                refreshed.raise_for_status()
                assert refreshed.json()["version_number"] == result["profile"]["version_number"]
                consecutive_failures = (
                    consecutive_failures + 1 if result["audit"].get("verdict") != "pass" else 0
                )
                if consecutive_failures >= 2:
                    break
            finally:
                CALL_DIRECTORY.reset(token)
        dump(
            directory / "result.json",
            {
                "group": mode,
                "turns": results,
                "disclosures": counts,
                "planned_turns": turns,
                "completed_turns": len(results),
                "aborted": len(results) < turns,
            },
        )
    Base.metadata.drop_all(bind=engine)


def freeze(out):
    manifest = {
        "version": "d4-grounding-experiment-20261014-v1",
        "groups": GROUPS,
        "hashes": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in FILES},
        "cases": CASES,
        "persona": PERSONA,
        "limits": {
            "recording_repeats": 1,
            "interview_turns": 14,
            "history_search": False,
            "automatic_retries": 0,
            "sol_connect_timeout_seconds": 20,
            "consecutive_failure_stop": 2,
        },
    }
    path = out / "frozen.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != json.loads(json.dumps(manifest)):
            raise ValueError("experiment_sources_changed_use_new_directory")
    else:
        dump(path, manifest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--track", choices=("recording", "interview", "all"), default="all")
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / "tmp"):
        raise ValueError("receipts_must_be_in_ignored_tmp")
    freeze(out)
    if not args.live:
        print("Materials frozen; use --live only for an authorized real-provider experiment.")
        return
    settings, isolated = bootstrap()
    from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

    if not all(
        OpenAICompatibleClient.for_task(task).capabilities().configured
        for task in ("interview", "interview_review")
    ):
        raise ValueError("experiment_credentials_unconfigured")
    receipt_transport()
    try:
        if args.track in {"recording", "all"}:
            jobs = [(deepcopy(case), mode) for case in CASES for mode in GROUPS]
            random.Random(20261014).shuffle(jobs)
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = [pool.submit(run_case, case, mode, out) for case, mode in jobs]
                for future in as_completed(futures):
                    result = future.result()
                    print(
                        json.dumps(
                            {
                                "track": "recording",
                                "case": result["case"],
                                "group": result["group"],
                                "verdict": result["audit"]["verdict"],
                                "elapsed_ms": result["audit"]["elapsed_ms"],
                            }
                        ),
                        flush=True,
                    )
        if args.track in {"interview", "all"}:
            for mode in GROUPS:
                interview(mode, out, 14)
    finally:
        isolated.pytest_sessionfinish()


if __name__ == "__main__":
    main()

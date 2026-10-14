"""Authorized live comparison through local app workflows, with isolated databases.

Run with apps/api/.venv/Scripts/python.exe. No Git or deployment operations.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

from interview_persona import ADAPTIVE_GOALS, ADAPTIVE_OPENING, NAME, PACKETS, VERSION

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api/src"))
MODELS = {
    "lite": ("volcengine", "doubao-seed-2-1-lite-260915"),
    "hybrid": ("volcengine", "doubao-seed-2-1-lite-260915"),
    "sol": ("inherit", "gpt-6.1-sol"),
}
CODE_PATHS = [
    "deploy/tests/interview_compare.py",
    "apps/api/src/lifereel_api/core/config.py",
    "services/interview/src/lifereel_api/modules/interview/companion.py",
    "services/interview/src/lifereel_api/modules/interview/profile_extraction.py",
    "services/interview/src/lifereel_api/modules/interview/profile_service.py",
    "services/interview/src/lifereel_api/modules/interview/profile_updates.py",
    "services/interview/src/lifereel_api/modules/interview/advice.py",
    "services/interview/src/lifereel_api/modules/interview/quality.py",
    "services/tasks/src/lifereel_api/modules/jobs/dispatch.py",
    "services/interview/src/lifereel_api/modules/orchestration/profile_turns.py",
    "services/interview/src/lifereel_api/modules/orchestration/service.py",
    "services/model-gateway/src/lifereel_api/providers/openai_compatible.py",
    "deploy/tests/interview_persona.py",
    "docs/interview-acceptance.md",
]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def digest():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in CODE_PATHS}


def configure(directory, model, live, read_timeout=25, turn_budget=75, *,
              quality=False, sync=False):
    from dotenv import dotenv_values

    credentials = dotenv_values(ROOT / ".env")
    for key in (
        "VOLCENGINE_API_BASE_URL",
        "VOLCENGINE_API_KEY",
        "OPENAI_COMPATIBLE_BASE_URL",
        "OPENAI_COMPATIBLE_API_KEY",
    ):
        if credentials.get(key):
            os.environ[key] = credentials[key]
    backend, name = MODELS[model]
    if live:
        prefix = "VOLCENGINE" if backend == "volcengine" else "OPENAI_COMPATIBLE"
        if not os.environ.get(f"{prefix}_API_KEY"):
            raise SystemExit("MODEL_CREDENTIAL_MISSING")
    settings = {
        "APP_ENV": "test",
        "SERVICE_MODE": "local",
        "LIFEREEL_SERVICE": "monolith",
        "DATABASE_URL": f"sqlite:///{(directory / 'isolated.db').as_posix()}",
        "AUTO_CREATE_SCHEMA": "true",
        "STORAGE_BACKEND": "local",
        "LOCAL_STORAGE_PATH": str(directory / "storage"),
        "LLM_PROVIDER": "openai-compatible" if live else "mock",
        "INTERVIEW_LLM_BACKEND": backend,
        "INTERVIEW_LLM_MODEL": name,
        "INTERVIEW_ENHANCEMENTS_ENABLED": "true",
        "INTERVIEW_HISTORY_ENABLED": "true",
        "INTERVIEW_REVIEW_ENABLED": "true" if model == "hybrid" else "false",
        "INTERVIEW_QUALITY_ENABLED": str(quality).lower(),
        "INTERVIEW_SYNC_ASSISTANCE_ENABLED": str(sync).lower(),
        "INTERVIEW_REVIEW_LLM_MODEL": "gpt-6.1-sol",
        "INTERVIEW_REVIEW_LLM_READ_TIMEOUT_SECONDS": "60",
        "JOB_QUEUE_BACKEND": "database",
        "INTERVIEW_LLM_STREAM": "false",
        "INTERVIEW_LLM_READ_TIMEOUT_SECONDS": str(read_timeout),
        "INTERVIEW_TURN_BUDGET_SECONDS": str(turn_budget),
        "INTERVIEW_LLM_CONNECT_TIMEOUT_SECONDS": "4",
        "INTERVIEW_LLM_WRITE_TIMEOUT_SECONDS": "5",
        "INTERVIEW_LLM_POOL_TIMEOUT_SECONDS": "3",
        "LLM_MIN_INTERVAL_SECONDS": "0.25",
        "REGISTRATION_ENABLED": "false",
        "SMS_ENABLED": "false",
        "ASR_PROVIDER": "mock",
        "IMAGE_PROVIDER": "mock",
        "VIDEO_PROVIDER": "mock",
        "VOICE_PROVIDER": "mock",
        "REALTIME_VOICE_PROVIDER": "disabled",
        "PHOTO_REDRAW_PROVIDER": "disabled",
        "OSS_DIRECT_UPLOAD_ENABLED": "false",
        "BILLING_TEXT_MODE": "per_successful_chapter_update",
        "BILLING_VIDEO_MODE": "per_second",
        "MANUAL_WECHAT_ENABLED": "false",
        "MANUAL_ALIPAY_ENABLED": "false",
        "BOOTSTRAP_OWNER_EMAIL": "",
        "BOOTSTRAP_OWNER_PASSWORD": "",
        "API_ACCESS_KEY": "",
        "AUTH_TOKEN_SECRET": "",
        "LOG_LEVEL": "WARNING",
    }
    os.environ.update(settings)
    from lifereel_api.core.config import get_settings

    get_settings.cache_clear()


def fixed_history(request, answer):
    # Live adapter returned no_results on 2026-10-13 for this exact public query.
    # Replay the same failure for both candidates; never fabricate a source.
    return {
        "status": "no_results",
        "sources": [],
        "evaluation_fixture": True,
        "limits": "固定查询无结果，不能据此否定用户记忆，也不能声称核实了公开事件。",
    }


def observe_transport(directory):
    import httpx

    original = httpx.post

    def post(*args, **kwargs):
        start = time.perf_counter()
        row = {
            "requested_model": kwargs.get("json", {}).get("model"),
            "messages": kwargs.get("json", {}).get("messages", []),
        }
        try:
            response = original(*args, **kwargs)
            row["http_status"] = response.status_code
            if response.is_success:
                data = response.json()
                row.update(
                    returned_model=data.get("model"),
                    usage=data.get("usage"),
                    choices=data.get("choices"),
                )
            return response
        except httpx.RequestError as exc:
            row["error_class"] = type(exc).__name__
            raise
        finally:
            row["seconds"] = round(time.perf_counter() - start, 3)
            with (directory / "model-calls.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    httpx.post = post


def export(client, directory, state):
    from sqlalchemy import select

    from lifereel_api.core.database import SessionLocal
    from lifereel_api.modules.billing.models import UsageEvent

    profile = client.get(f"/v1/life-profiles/{state['profile_id']}").json()
    write_json(directory / "final-profile.json", profile)
    write_json(
        directory / "history.json",
        client.get(f"/v1/life-profiles/{state['profile_id']}/history").json(),
    )
    with SessionLocal() as db:
        usage = [
            {
                "model": row.model,
                "status": row.status,
                "usage": row.usage,
                "duration_ms": row.duration_ms,
                "error_code": row.error_code,
            }
            for row in db.scalars(select(UsageEvent).order_by(UsageEvent.created_at))
        ]
    write_json(directory / "usage.json", usage)
    transcript = (
        [
            json.loads(line)
            for line in (directory / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        if (directory / "transcript.jsonl").exists()
        else []
    )
    write_json(
        directory / "summary.json",
        {
            "model": state["model"],
            "phase": state["phase"],
            "turns": len(transcript),
            "completed": sum(t["status"] == "completed" for t in transcript),
            "failed": sum(t["status"] != "completed" for t in transcript),
            "calls": len(usage),
            "code_unchanged": digest() == state["code_hashes"],
            "history_mode": "fixed_fixture_not_live_search",
        },
    )
    return profile


def turn(client, directory, state, item):
    from lifereel_api.core.config import get_settings
    from lifereel_api.core.database import SessionLocal
    from lifereel_api.core.errors import ApiError
    from lifereel_api.modules.interview.models import InterviewTurnWorkflow
    from lifereel_api.modules.orchestration.service import execute_turn

    before = client.get(f"/v1/life-profiles/{state['profile_id']}").json()
    start = time.perf_counter()
    submitted = client.post(
        f"/v1/interviews/{state['session_id']}/turns",
        json={
            "answer_text": item["answer"],
            "idempotency_key": str(uuid4()),
        },
    )
    if submitted.status_code != 202:
        raise RuntimeError(f"SUBMISSION_{submitted.status_code}: {submitted.text[:300]}")
    workflow_id = submitted.json()["id"]
    with SessionLocal() as db:
        try:
            workflow = execute_turn(db, get_settings().default_tenant_id, UUID(workflow_id))
        except ApiError:
            db.rollback()
            workflow = db.get(InterviewTurnWorkflow, UUID(workflow_id))
            if workflow.status != "failed":
                raise
        result = {
            "number": state["turns"] + 1,
            "packet_id": item["id"],
            "case": item["case"],
            "answer": item["answer"],
            "fact_ids": [f["id"] for f in item.get("facts", [])],
            "disclosure": item.get("disclosure", "tester_led"),
            "status": workflow.status,
            "error_code": workflow.error_code,
            "reply": workflow.next_question or "",
            "result": workflow.profile_result,
            "seconds": round(time.perf_counter() - start, 3),
            "before_version": before["version_number"],
        }
    profile = client.get(f"/v1/life-profiles/{state['profile_id']}").json()
    result["after_version"] = profile["version_number"]
    with (directory / "transcript.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False) + "\n")
    write_json(directory / f"profile-{result['number']:02}.json", profile)
    state["turns"] += 1
    write_json(directory / "state.json", state)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "number",
                    "packet_id",
                    "status",
                    "error_code",
                    "seconds",
                    "reply",
                )
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if state.get("mode") == "hybrid":
        # Explicit evaluation pause between answers, not part of user reply latency.
        # This measures usable advice, not its hit rate during rapid concurrent turns.
        from sqlalchemy import select

        from lifereel_api.modules.interview import advice
        from lifereel_api.modules.jobs import dispatch
        from lifereel_api.modules.jobs.models import Job

        with SessionLocal() as db:
            job = db.scalar(select(Job).where(Job.kind == advice.KIND, Job.status == "queued"))
            if job:
                advice_start = time.perf_counter()
                claim = dispatch.claim_job(db, "interview")
                if claim and claim["job_id"] == str(job.id):
                    dispatch.execute_claim(db, job.id, UUID(claim["token"]))
                    write_json(directory / f"advice-{result['number']:02}.json", {
                        "status": job.status, "result": job.result,
                        "error_code": job.error_code,
                        "seconds": round(time.perf_counter() - advice_start, 3),
                        "evaluation_pause_between_answers": True,
                    })
    return result


def recover_failed_turn(client, directory, state):
    from sqlalchemy import select

    from lifereel_api.core.database import SessionLocal
    from lifereel_api.modules.interview.models import InterviewRound, InterviewTurnWorkflow

    item = PACKETS[state["turns"]]
    with SessionLocal() as db:
        workflow = db.scalar(
            select(InterviewTurnWorkflow)
            .where(InterviewTurnWorkflow.session_id == UUID(state["session_id"]))
            .order_by(InterviewTurnWorkflow.created_at.desc())
            .limit(1)
        )
        answer = db.get(InterviewRound, workflow.round_id).answer_text
        if workflow.status != "failed" or answer != item["answer"]:
            raise SystemExit("NO_MATCHING_ORPHAN_FAILURE")
        result = {
            "number": state["turns"] + 1,
            "packet_id": item["id"],
            "case": item["case"],
            "answer": answer,
            "fact_ids": [f["id"] for f in item["facts"]],
            "disclosure": "tester_led",
            "status": workflow.status,
            "error_code": workflow.error_code,
            "reply": workflow.next_question or "",
            "result": workflow.profile_result,
            "seconds": None,
            "timing_note": "Original harness raised after failure; full turn latency unavailable.",
            "recovered_without_provider_retry": True,
        }
    with (directory / "transcript.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False) + "\n")
    profile = client.get(f"/v1/life-profiles/{state['profile_id']}").json()
    write_json(directory / f"profile-{result['number']:02}.json", profile)
    state["turns"] += 1
    write_json(directory / "state.json", state)
    print(json.dumps(result, ensure_ascii=False), flush=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=MODELS, required=True)
    parser.add_argument("--phase", choices=["recording", "adaptive"], default="recording")
    parser.add_argument("--run", default="baseline")
    parser.add_argument("--live", action="store_true", help="Explicitly authorized paid LLM calls")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--answer")
    parser.add_argument("--persona-name", default=NAME)
    parser.add_argument("--persona-spec", type=Path, help="Hidden holdout specification; hash only")
    parser.add_argument("--disclosure", choices=["answer_to_ai", "tester_led", "opening"])
    parser.add_argument("--fact", action="append", default=[])
    parser.add_argument("--recover-failed-turn", action="store_true")
    parser.add_argument("--read-timeout", type=float, default=25)
    parser.add_argument("--turn-budget", type=float, default=75)
    parser.add_argument("--quality", action="store_true")
    parser.add_argument("--sync-assistance", action="store_true")
    args = parser.parse_args()
    if not args.run or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in args.run):
        parser.error("run must be a simple local identifier")
    if not 1 <= args.read_timeout <= 90 or not 10 <= args.turn_budget <= 300:
        parser.error("bounded read timeout (1..90) and turn budget (10..300) required")
    if args.sync_assistance and (not args.quality or args.model != "hybrid"):
        parser.error("sync assistance requires hybrid and quality")
    holdout_spec = None
    if args.persona_spec:
        if args.phase != "adaptive":
            parser.error("holdout specification requires adaptive phase")
        path = args.persona_spec.resolve()
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            parser.error("holdout specification must be in this workspace")
        holdout_spec = {"path": relative.as_posix(),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    directory = ROOT / "tmp/interview-compare-20261013" / args.run / args.phase / args.model
    directory.mkdir(parents=True, exist_ok=True)
    configure(directory, args.model, args.live, args.read_timeout, args.turn_budget,
              quality=args.quality, sync=args.sync_assistance)
    request_settings = {"read_timeout": args.read_timeout, "turn_budget": args.turn_budget,
                        "quality": args.quality, "sync_assistance": args.sync_assistance}
    from fastapi.testclient import TestClient

    from lifereel_api.main import app
    from lifereel_api.modules.interview import historical_context

    historical_context.lookup = fixed_history
    if args.live:
        observe_transport(directory)
    with TestClient(app) as client:
        state_path = directory / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if (
                state["live"] != args.live
                or state.get("persona_name", NAME) != args.persona_name
                or state.get("holdout_spec") != holdout_spec
                or state.get("request_settings", {"read_timeout": 25, "turn_budget": 75})
                != request_settings
            ):
                raise SystemExit("FROZEN_REQUEST_SETTINGS_CHANGED_USE_NEW_RUN")
            changed = {
                path for path, sha in digest().items() if state["code_hashes"].get(path) != sha
            }
            if changed == {"deploy/tests/interview_compare.py"} and args.recover_failed_turn:
                state.setdefault("harness_revisions", []).append(state["code_hashes"])
                state["code_hashes"] = digest()
                write_json(state_path, state)
            elif changed or state["live"] != args.live:
                raise SystemExit("FROZEN_CONDITION_CHANGED_USE_NEW_RUN")
        else:
            if (directory / "transcript.jsonl").exists():
                raise SystemExit("ORPHAN_TRANSCRIPT_DO_NOT_OVERWRITE")
            person = client.post("/v1/persons", json={"display_name": args.persona_name})
            person.raise_for_status()
            session = client.post("/v1/interviews", json={"subject_id": person.json()["id"]})
            session.raise_for_status()
            session_data = session.json()
            state = {
                "mode": args.model,
                "model": MODELS[args.model][1],
                "backend": MODELS[args.model][0],
                "phase": args.phase,
                "persona_version": f"sha256:{holdout_spec['sha256']}" if holdout_spec else VERSION,
                "persona_name": args.persona_name,
                "holdout_spec": holdout_spec,
                "live": args.live,
                "request_settings": request_settings,
                "session_id": session_data["id"],
                "profile_id": session_data["profile_id"],
                "code_hashes": digest(),
                "turns": 0,
                "adaptive_goals": "See frozen holdout specification" if holdout_spec
                else ADAPTIVE_GOALS,
            }
            write_json(state_path, state)
            write_json(
                directory / "initial-profile.json",
                client.get(f"/v1/life-profiles/{state['profile_id']}").json(),
            )
        if args.recover_failed_turn:
            recover_failed_turn(client, directory, state)
        if args.phase == "recording":
            for item in PACKETS[state["turns"] : args.limit]:
                turn(client, directory, state, item)
        elif args.answer or state["turns"] == 0:
            facts = {f["id"]: f for p in PACKETS for f in p["facts"]}
            turn(
                client,
                directory,
                state,
                {
                    "id": f"A{state['turns'] + 1:02}",
                    "case": "adaptive",
                    "answer": args.answer or ADAPTIVE_OPENING,
                    "facts": [{"id": key} for key in args.fact] if holdout_spec else [
                        facts[key] for key in args.fact
                    ],
                    "disclosure": args.disclosure
                    or ("answer_to_ai" if state["turns"] else "opening"),
                },
            )
        export(client, directory, state)


if __name__ == "__main__":
    main()

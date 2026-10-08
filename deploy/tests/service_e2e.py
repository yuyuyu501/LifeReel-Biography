"""Run only against the named local QA stack; never accepts a production target."""

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]


def script_content(project):
    """Check generated prose, not UUIDs, timestamps or other metadata."""
    scene_fields = (
        "heading", "plot", "narration", "visual_prompt", "dialogues",
        "visual_constraints", "story_skeleton",
    )
    return json.dumps(
        {
            "title": project["title"],
            "scenes": [{k: scene.get(k) for k in scene_fields} for scene in project["scenes"]],
            "shots": [
                {k: shot.get(k) for k in ("visual_prompt", "visual_constraints")}
                for shot in project["shots"]
            ],
        },
        ensure_ascii=False,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:5189")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if urlparse(args.url).hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("LOCAL_QA_ONLY")
    env_file = args.env_file.resolve()
    if ROOT not in env_file.parents or "tmp" not in env_file.parts:
        raise SystemExit("QA_ENV_MUST_BE_IN_WORKSPACE_TMP")
    values = {}
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value
    if any(
        values.get(name) != "mock" for name in ("LLM_PROVIDER", "ASR_PROVIDER", "VIDEO_PROVIDER")
    ):
        raise SystemExit("MOCK_PROVIDERS_REQUIRED")
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-p",
        "lifereel-servicesqa",
        "-f",
        str(ROOT / "compose.production.yaml"),
    ]
    checks = []

    def docker(*arguments):
        result = subprocess.run(
            [*compose, *arguments], cwd=ROOT, capture_output=True, text=True, timeout=180
        )
        if result.returncode:
            raise AssertionError(f"QA_DOCKER_COMMAND_FAILED:{arguments[0]}")
        return result.stdout

    def checked(name, **details):
        checks.append({"test": name, "status": "passed", **details})
        print(json.dumps(checks[-1], ensure_ascii=False), flush=True)

    def wait_for(callback, seconds=90):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            try:
                value = callback()
            except httpx.RequestError:
                value = None
            if value:
                return value
            time.sleep(1)
        raise AssertionError("QA_CONDITION_TIMEOUT")

    stopped = set()
    try:
        with httpx.Client(base_url=args.url, timeout=90, trust_env=False) as client:

            def request(method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                if not response.is_success:
                    raise AssertionError(
                        f"HTTP_{response.status_code}:{path}:{response.text[:500]}"
                    )
                return response.json()

            wait_for(lambda: client.get("/ready").status_code == 200)
            request(
                "POST",
                "/v1/auth/login",
                json={
                    "email": values["BOOTSTRAP_OWNER_EMAIL"],
                    "password": values["BOOTSTRAP_OWNER_PASSWORD"],
                },
            )
            assert "text/html" in client.get("/").headers.get("content-type", "")
            checked("web_gateway_login_and_readiness")
            for path in ("/v1/internal/worker/claim", "/internal/v1/billing.reserve"):
                assert client.post(path, json={}).status_code == 404
            checked("internal_routes_are_not_public")
            request("GET", "/v1/wallet")
            person = request("POST", "/v1/persons", json={"display_name": "服务拆分合成测试"})
            # This database is exclusively synthetic. Seed repeatable QA funds,
            # without contacting recharge or changing any production wallet.
            from uuid import UUID

            subject_id = str(UUID(person["id"]))
            docker(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "lifereel",
                "-d",
                "lifereel",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "UPDATE billing.wallets SET bonus_cents=1000000 WHERE tenant_id="
                f"(SELECT tenant_id FROM identity.persons WHERE id='{subject_id}')"
                " AND frozen_bonus_cents=0 AND frozen_paid_cents=0",
            )
            wallet_before = request("GET", "/v1/wallet")
            chapter = request("GET", "/v1/chapters")[0]
            session = request(
                "POST",
                "/v1/interviews",
                json={
                    "mode": "legacy",
                    "subject_id": person["id"],
                    "chapter_id": chapter["id"],
                },
            )
            turn_url = f"/v1/interviews/{session['id']}/turns"
            workspace_url = f"/v1/interviews/{session['id']}/workspace"
            payload = {
                "round_id": session["rounds"][-1]["id"],
                "answer_text": (
                    "1988年，我在泉州的小学上学，父亲骑自行车送我，老师鼓励我朗读。"
                    "我起初害怕，后来很开心，这让我喜欢阅读。"
                ),
                "idempotency_key": f"services-qa-{uuid4()}",
            }
            # A stopped publisher must leave the committed turn queued, then recover it.
            docker("stop", "tasks")
            stopped.add("tasks")
            turn = request("POST", turn_url, json=payload)
            assert turn["status"] == "queued"
            time.sleep(3)
            assert request("GET", workspace_url)["latest_workflow"]["status"] == "queued"
            docker("start", "tasks")
            stopped.remove("tasks")

            def completed():
                workspace = request("GET", workspace_url)
                workflow = workspace["latest_workflow"]
                if workflow["status"] == "failed":
                    raise AssertionError(f"WORKFLOW_FAILED:{workflow['error_code']}")
                return workspace if workflow["status"] == "completed" else None

            workspace = wait_for(completed)
            checked("outbox_recovers_after_publisher_restart", workflow_id=turn["id"])
            assert workspace["script"] and workspace["latest_workflow"]["source_claim_ids"]
            assert workspace["latest_workflow"]["next_question"]
            wait_for(lambda: request("GET", "/v1/wallet")["frozen_cents"] == 0)
            consumption_before = request("GET", "/v1/wallet/ledger", params={"event": "consume"})[
                "total"
            ]
            replay = request("POST", turn_url, json=payload)
            assert replay["id"] == turn["id"]
            assert (
                request("GET", "/v1/wallet/ledger", params={"event": "consume"})["total"]
                == consumption_before
            )
            checked(
                "interview_memory_script_and_idempotent_wallet",
                subject_id=person["id"],
                script_project_id=workspace["latest_workflow"]["script_project_id"],
            )
            # Exercise the correction through real HTTP and independent workers.
            revision_payload = {
                "action": "revise_answer",
                "round_id": payload["round_id"],
                "expected_version": 1,
                "answer_text": (
                    "1989年，我在漳州的小学上学，父亲骑自行车送我，老师鼓励我朗读。"
                    "我起初害怕，后来很开心，这让我喜欢阅读。"
                ),
                "idempotency_key": f"experience-qa-revise-{uuid4()}",
            }
            revision = request("POST", turn_url, json=revision_payload)
            workspace = wait_for(completed)
            current_session = request("GET", f"/v1/interviews/{session['id']}")
            revised_round = next(
                r for r in current_session["rounds"] if r["id"] == payload["round_id"]
            )
            assert revised_round["answer_version"] == 2
            assert revised_round["answer_text"] == revision_payload["answer_text"]
            assert revised_round["answer_revisions"][0]["text"] == payload["answer_text"]
            assert workspace["progress"]["stage"] == "completed"
            assert workspace["latest_workflow"]["script_brief"]["response_completed_at"]
            assert request("POST", turn_url, json=revision_payload)["id"] == revision["id"]
            assert (
                client.post(
                    turn_url, json={**revision_payload, "idempotency_key": str(uuid4())}
                ).status_code
                == 409
            )
            claims = request("GET", "/v1/memories", params={"subject_id": subject_id})
            current = next(c for c in claims if c["source_round_id"] == payload["round_id"])
            assert current["source_quote"] == revision_payload["answer_text"]
            timeline = request("GET", f"/v1/memories/subjects/{subject_id}/timeline")
            assert any(t["year"] == 1989 for t in timeline)
            assert not any(t["year"] == 1988 for t in timeline)
            project_json = script_content(workspace["script"])
            assert "漳州" in project_json and "泉州" not in project_json
            assert "1989" in project_json and "1988" not in project_json
            wait_for(lambda: request("GET", "/v1/wallet")["frozen_cents"] == 0)
            checked(
                "revision_updates_memory_timeline_script_and_keeps_history",
                workflow_id=revision["id"],
            )
            project_id = workspace["latest_workflow"]["script_project_id"]
            project = request("GET", f"/v1/scripts/{project_id}")
            scene_id = project["scenes"][0]["id"]
            run = request(
                "POST",
                "/v1/production/runs",
                json={
                    "project_id": project_id,
                    "scene_id": scene_id,
                    "provider": "mock",
                    "audience": "private",
                },
            )

            def video_completed():
                runs = request("GET", "/v1/production/runs")
                current = next(item for item in runs if item["id"] == run["id"])
                if current["status"] == "failed":
                    raise AssertionError(f"VIDEO_FAILED:{current['error_message']}")
                return current if current["status"] == "completed" else None

            run = wait_for(video_completed, seconds=150)
            asset = run["assets"][0]
            media = client.get(f"/v1/production/assets/{asset['id']}/content")
            assert media.status_code == 200 and len(media.content) > 32
            assert hashlib.sha256(media.content).hexdigest() == asset["sha256"]
            ranged = client.get(
                f"/v1/production/assets/{asset['id']}/content", headers={"Range": "bytes=0-31"}
            )
            assert ranged.status_code == 206 and ranged.content == media.content[:32]
            checked("media_worker_video_hash_and_range", run_id=run["id"], sha256=asset["sha256"])
            docker("stop", "memory")
            stopped.add("memory")
            assert client.get("/ready").status_code == 503
            assert client.get("/v1/persons").status_code == 200
            assert client.get("/v1/wallet").status_code == 200
            checked("memory_failure_isolated_and_readiness_degraded")
            consumption_at_failure = request(
                "GET", "/v1/wallet/ledger", params={"event": "consume"}
            )["total"]
            latest_session = request("GET", f"/v1/interviews/{session['id']}")
            failure_payload = {
                "round_id": latest_session["rounds"][-1]["id"],
                "answer_text": "1992年我进入中学，参加学校的读书活动，周末和父亲去图书馆。",
                "idempotency_key": f"services-qa-failure-{uuid4()}",
            }
            failed_turn = request("POST", turn_url, json=failure_payload)
            wait_for(lambda: request("GET", workspace_url)["latest_workflow"]["status"] == "failed")
            wait_for(lambda: request("GET", "/v1/wallet")["frozen_cents"] == 0)
            assert (
                request("GET", "/v1/wallet/ledger", params={"event": "consume"})["total"]
                == consumption_at_failure
            )
            checked("failed_cross_service_task_releases_hold_without_consumption")
            docker("start", "memory")
            stopped.remove("memory")
            wait_for(lambda: client.get("/ready").status_code == 200)

            def retry_when_allowed():
                response = client.post(f"/v1/jobs/{failed_turn['job_id']}/retry")
                if (
                    response.status_code == 409
                    and response.json().get("error", {}).get("code") == "MEMORY_RETRY_COOLDOWN"
                ):
                    return None
                assert response.is_success, response.text
                return response.json()

            wait_for(retry_when_allowed, seconds=180)
            wait_for(completed)
            wait_for(lambda: request("GET", "/v1/wallet")["frozen_cents"] == 0)
            assert (
                request("GET", "/v1/wallet/ledger", params={"event": "consume"})["total"]
                == consumption_at_failure + 1
            )
            assert request("POST", turn_url, json=failure_payload)["id"] == failed_turn["id"]
            checked("recovered_job_retries_through_owner_and_consumes_once")
            final_wallet = request("GET", "/v1/wallet")
            assert final_wallet["available_cents"] < wallet_before["available_cents"]
            assert final_wallet["frozen_cents"] == 0
            checked(
                "services_recover_without_duplicate_charges",
                initial_script_consumptions=consumption_before,
            )
            versions = docker(
                "exec",
                "-T",
                "tasks",
                "python",
                "-c",
                "from lifereel_api.core.database import engine; from sqlalchemy import text; "
                "c=engine.connect(); "
                "print(c.execute(text('select version_num from public.alembic_version')).scalar())",
            )
            expected_head = docker(
                "exec",
                "-T",
                "tasks",
                "python",
                "-c",
                "from alembic.config import Config; from alembic.script import ScriptDirectory; "
                "c=Config('/workspace/apps/api/alembic.ini'); "
                "c.set_main_option('script_location','/workspace/apps/api/alembic'); "
                "print(ScriptDirectory.from_config(c).get_current_head())",
            )
            assert versions.strip() == expected_head.strip()
            checked("migration_runtime_version", version=versions.strip())
            layout = docker(
                "exec",
                "-T",
                "tasks",
                "python",
                "-c",
                "import json; from sqlalchemy import inspect; "
                "from lifereel_api.core.database import Base,engine; "
                "from lifereel_api.core.schema import SERVICE_SCHEMAS; "
                "from lifereel_api.architecture.metadata import register_models; "
                "register_models(); "
                "expected={s:sorted(t.name for t in Base.metadata.tables.values() if t.schema==s) "
                "for s in SERVICE_SCHEMAS}; "
                "actual={s:sorted(inspect(engine).get_table_names(schema=s)) "
                "for s in SERVICE_SCHEMAS}; "
                "assert actual==expected,(actual,expected); "
                "assert set(inspect(engine).get_table_names(schema='public'))"
                "=={'alembic_version'}; "
                "print(json.dumps({s:len(t) for s,t in actual.items()}))",
            )
            checked("single_database_service_schemas", tables=json.loads(layout))
    except Exception as exc:
        checks.append({"test": "suite", "status": "failed", "error": str(exc)[:1000]})
        raise
    finally:
        for name in sorted(stopped):
            docker("start", name)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(checks, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

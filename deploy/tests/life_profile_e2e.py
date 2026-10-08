"""Synthetic integration of the profile → saved book → script → video flow.

Only localhost and the lifereel-lifeqa Docker project with mock providers are allowed.
"""

import argparse
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--synthetic-book-overlay", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:5198")
    args = parser.parse_args()
    if urlparse(args.url).hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("LOCAL_QA_ONLY")
    env_file = args.env_file.resolve()
    if ROOT not in env_file.parents or "tmp" not in env_file.parts:
        raise SystemExit("QA_ENV_MUST_BE_IN_TMP")
    env = dotenv_values(env_file)
    if any(
        env.get(k) != "mock"
        for k in ["LLM_PROVIDER", "ASR_PROVIDER", "VIDEO_PROVIDER", "IMAGE_PROVIDER"]
    ):
        raise SystemExit("MOCK_PROVIDERS_REQUIRED")
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-p",
        "lifereel-lifeqa",
        "-f",
        str(ROOT / "compose.production.yaml"),
    ]
    if args.synthetic_book_overlay:
        overlay = args.synthetic_book_overlay.resolve()
        if ROOT not in overlay.parents or "tmp" not in overlay.parts:
            raise SystemExit("QA_OVERLAY_MUST_BE_IN_TMP")
        data = json.loads(overlay.read_text(encoding="utf-8"))
        assert set(data["services"]) == {"qa-book-model", "worker-book", "model-gateway"}
        for name in ("worker-book", "model-gateway"):
            assert data["services"][name]["environment"]["OPENAI_COMPATIBLE_BASE_URL"] == (
                "http://qa-book-model:8080/v1"
            )
        compose += ["-f", str(overlay)]
    def sql(query):
        return docker(
            "exec", "-T", "postgres", "psql", "-U", "lifereel", "-d", "lifereel",
            "-v", "ON_ERROR_STOP=1", "-Atc", query,
        ).strip()

    checks = []
    stopped = set()

    def checked(name, **details):
        checks.append({"test": name, "status": "passed", **details})
        print(json.dumps(checks[-1], ensure_ascii=False), flush=True)

    def docker(*command):
        return subprocess.check_output(
            [*compose, *command], cwd=ROOT, text=True, stderr=subprocess.STDOUT
        )

    def wait(callback, seconds=120):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            try:
                result = callback()
                if result:
                    return result
            except httpx.RequestError:
                pass
            time.sleep(1)
        raise AssertionError("QA_CONDITION_TIMEOUT")

    try:
        with httpx.Client(base_url=args.url, timeout=90, trust_env=False) as client:

            def request(method, path, **kwargs):
                result = client.request(method, path, **kwargs)
                assert result.is_success, f"{path}:HTTP_{result.status_code}:{result.text[:300]}"
                return result.json()

            wait(lambda: client.get("/ready").is_success)
            request(
                "POST",
                "/v1/auth/login",
                json={
                    "email": env["BOOTSTRAP_OWNER_EMAIL"],
                    "password": env["BOOTSTRAP_OWNER_PASSWORD"],
                },
            )
            checked("independent_services_ready_and_login")
            person = request("POST", "/v1/persons", json={"display_name": "人生流程合成验证"})
            subject = person["id"]
            request("GET", "/v1/wallet")
            docker(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "lifereel",
                "-d",
                "lifereel",
                "-c",
                "UPDATE billing.wallets SET bonus_cents=1000000 WHERE tenant_id="
                "(SELECT tenant_id FROM identity.persons WHERE id='" + subject + "')",
            )
            session = request("POST", "/v1/interviews", json={"subject_id": subject})
            assert not session["chapter_id"] and session["profile_id"]
            assert (
                request("POST", "/v1/interviews", json={"subject_id": subject})["id"]
                == session["id"]
            )
            workspace_url = f"/v1/interviews/{session['id']}/workspace"
            turn_url = f"/v1/interviews/{session['id']}/turns"
            payload = {
                "answer_text": "1988年，我去泉州的工厂做工。",
                "idempotency_key": str(uuid4()),
            }
            docker("stop", "tasks")
            stopped.add("tasks")
            turn = request("POST", turn_url, json=payload)
            assert turn["status"] == "queued"
            docker("start", "tasks")
            stopped.remove("tasks")

            def completed():
                workspace = request("GET", workspace_url)
                workflow = workspace["latest_workflow"]
                assert workflow["status"] != "failed", workflow.get("error_code")
                return workspace if workflow["status"] == "completed" else None

            workspace = wait(completed)
            assert (
                workspace["script"] is None
                and not workspace["latest_workflow"]["script_project_id"]
            )
            assert request("POST", turn_url, json=payload)["id"] == turn["id"]
            checked("profile_interview_no_script_and_publisher_restart")
            request(
                "POST",
                turn_url,
                json={
                    "answer_text": "更正一下，不是1988年，应该是1989年，去漳州的工厂做工。",
                    "idempotency_key": str(uuid4()),
                },
            )
            workspace = wait(completed)
            profile = workspace["profile"]
            events = [e for e in profile["entries"] if e["field_key"] == "work.events[]"]
            assert (
                len(events) == 1
                and "1988" not in str(events[0]["value"])
                and "1989" in str(events[0]["value"])
                and events[0]["value"].get("place") == "漳州"
            )
            assert not any(e["field_key"] == "identity.gender" for e in profile["entries"])
            checked("second_turn_corrects_same_event_without_invented_gender")
            event = events[0]
            value = {
                **event["value"],
                "what": "我在漳州工厂做工，核对单据遇到漏记就找同事逐项检查。" * 4,
                "action": "我主动核对单据并和同事补齐记录。",
                "impact": "后来我学会耐心，也能独立处理记录。",
            }
            edit = {
                "expected_version": profile["version_number"],
                "request_id": str(uuid4()),
                "changes": [
                    {
                        "field_key": event["field_key"],
                        "record_key": event["record_key"],
                        "id": event["id"],
                        "value": value,
                    }
                ],
            }
            docker("stop", "memory")
            stopped.add("memory")
            assert client.patch(f"/v1/life-profiles/{profile['id']}", json=edit).status_code == 503
            profile = request("GET", f"/v1/life-profiles/{profile['id']}")
            assert profile["version_number"] == edit["expected_version"] + 1
            docker("start", "memory")
            stopped.remove("memory")
            wait(lambda: client.get("/ready").is_success)
            # Entries and the complete profile have independent version counters.
            saved_entry = next(e for e in profile["entries"] if e["id"] == event["id"])
            # Observe durable outbox recovery before replaying the client PATCH.
            wait(lambda: sql(
                "SELECT count(*) FROM memory.memory_claims WHERE profile_entry_id='"
                + event["id"] + "' AND source_revision=" + str(saved_entry["version_number"])
            ) == "1")
            assert (
                request("PATCH", f"/v1/life-profiles/{profile['id']}", json=edit)["version_number"]
                == profile["version_number"]
            )
            checked("committed_profile_and_durable_memory_recovery")
            assert (
                client.get(f"/v1/life-profiles/{profile['id']}/export?format=xlsx").content[:2]
                == b"PK"
            )
            book = request("POST", "/v1/books", json={"subject_id": subject})
            chapter = book["chapters"][0]
            if args.synthetic_book_overlay:
                generation = {"idempotency_key": str(uuid4())}
                queued = request("POST", f"/v1/books/{book['id']}/generate", json=generation)
                assert request(
                    "POST", f"/v1/books/{book['id']}/generate", json=generation
                )["job_ids"] == queued["job_ids"]

                def book_done():
                    current_book = request("GET", f"/v1/books/{book['id']}")
                    current_chapter = current_book["chapters"][0]
                    assert current_chapter["status"] != "failed", current_chapter
                    return current_book if current_chapter["current"] else None

                book = wait(book_done)
                chapter = book["chapters"][0]
                assert 900 <= chapter["current"]["word_count"] <= 1100
                assert chapter["current"]["author"] == "ai"
                checked("worker_book_and_model_gateway_synthetic_1000_words")
            book = request(
                "PATCH",
                f"/v1/books/{book['id']}/chapters/{chapter['chapter_id']}",
                json={
                    "expected_version": chapter["version_number"],
                    "title": chapter["title"],
                    "body": (
                        "1989年，我在漳州的工厂做工。"
                        "我认真核对单据，和同事解决漏记问题，这让我学会耐心。"
                    )
                    * 25,
                },
            )
            revision = book["chapters"][0]["current"]
            draft = {
                "subject_id": subject,
                "book_revision_ids": [revision["id"]],
                "duration_seconds": 60,
                "idempotency_key": str(uuid4()),
                "adaptation_instructions": "全部镜头不露脸",
                "audience": "family",
            }
            project = request("POST", "/v1/scripts/generate", json=draft)
            assert project["source_type"] == "book" and len(project["scenes"]) == 2
            assert request("POST", "/v1/scripts/generate", json=draft)["id"] == project["id"]
            run = request(
                "POST",
                "/v1/production/runs",
                json={
                    "project_id": project["id"],
                    "scene_id": project["scenes"][0]["id"],
                    "audience": "family",
                    "provider": "mock",
                },
            )

            def video_done():
                runs = request("GET", "/v1/production/runs")
                current = next(r for r in runs if r["id"] == run["id"])
                assert current["status"] != "failed", current.get("error_message")
                return current if current["status"] == "completed" else None

            run = wait(video_done)
            assert run["assets"]
            assert client.get(f"/v1/production/assets/{run['assets'][0]['id']}/content").is_success
            wait(lambda: request("GET", "/v1/wallet")["frozen_cents"] == 0)
            checked(
                "saved_book_to_checkpointed_script_and_worker_video",
                scenes=len(project["scenes"]),
                book_version=revision["version_number"],
            )
            request(
                "PATCH",
                f"/v1/life-profiles/{profile['id']}",
                json={
                    "expected_version": profile["version_number"],
                    "request_id": str(uuid4()),
                    "changes": [
                        {
                            "id": event["id"],
                            "field_key": event["field_key"],
                            "record_key": event["record_key"],
                            "value": value,
                            "use_scope": "internal",
                        }
                    ],
                },
            )
            assert client.get(f"/v1/books/{book['id']}/export").status_code == 409
            draft["idempotency_key"] = str(uuid4())
            assert client.post("/v1/scripts/generate", json=draft).status_code == 409
            checked("private_source_blocks_exports_and_new_adaptation")
            paths = [
                "/ready",
                "/v1/persons",
                f"/v1/life-profiles/{profile['id']}",
                f"/v1/books/{book['id']}",
            ]

            def probe(index):
                start = time.monotonic()
                result = client.get(paths[index % len(paths)])
                return result.status_code, time.monotonic() - start

            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(probe, range(120)))
            assert all(code == 200 for code, _ in results)
            times = sorted(elapsed for _, elapsed in results)
            checked(
                "bounded_8_client_read_load",
                requests=len(results),
                failures=0,
                p95_seconds=round(times[int(len(times) * 0.95) - 1], 3),
            )
    finally:
        for name in stopped:
            docker("start", name)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "checks": checks,
                    "providers": "mock; book HTTP endpoint synthetic"
                    if args.synthetic_book_overlay else "mock",
                    "writing": "saved synthetic manuscript; literary quality not evaluated",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()

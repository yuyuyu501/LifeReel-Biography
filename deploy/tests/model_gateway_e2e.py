"""Exercise real service HTTP against an isolated, free synthetic model."""

import argparse
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.env_file.resolve()
    if ROOT not in source.parents or "tmp" not in source.parts:
        raise SystemExit("LOCAL_QA_CONFIG_REQUIRED")
    values = dict(
        line.split("=", 1)
        for line in source.read_text(encoding="utf-8-sig").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    if any(values.get(key) != "mock" for key in ("LLM_PROVIDER", "ASR_PROVIDER", "VIDEO_PROVIDER")):
        raise SystemExit("MOCK_QA_REQUIRED")
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(source),
        "-p",
        "lifereel-servicesqa",
        "-f",
        str(ROOT / "compose.production.yaml"),
    ]
    name = "lifereel-servicesqa-provider"
    overlay = source.parent / "synthetic-model.json"
    overlay.write_text(
        json.dumps(
            {
                "services": {
                    "model-gateway": {
                        "environment": {
                            "LLM_PROVIDER": "openai-compatible",
                            "OPENAI_COMPATIBLE_BASE_URL": f"http://{name}:8766/v1",
                            "OPENAI_COMPATIBLE_API_KEY": "synthetic-only",
                            "OPENAI_COMPATIBLE_MODEL": "synthetic-model",
                            "INTERVIEW_LLM_MODEL": "synthetic-model",
                            "LLM_STREAM": "false",
                            "INTERVIEW_LLM_STREAM": "false",
                            "BILLING_TEXT_MODE": "per_successful_chapter_update",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def run(command, check=True):
        action = next(
            (item for item in command if item in {"run", "up", "exec", "cp", "rm"}), "command"
        )
        print(json.dumps({"qa_docker_operation": action}), flush=True)
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=240)
        if check and result.returncode:
            raise RuntimeError("QA_COMMAND_FAILED: " + result.stderr[-1400:])
        return result

    created = False
    result = {"status": "failed"}
    try:
        run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--read-only",
                "--network",
                "lifereel-servicesqa_default",
                "--mount",
                f"type=bind,source={ROOT / 'deploy/tests/fake_model.py'},target=/fake.py,readonly",
                "--entrypoint",
                "python",
                f"lifereel/backend-runtime:{values['LIFEREEL_RELEASE']}",
                "/fake.py",
            ]
        )
        created = True
        run([*compose, "-f", str(overlay), "up", "-d", "--no-deps", "model-gateway"])
        for _ in range(45):
            ready = run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "model-gateway",
                    "python",
                    "-c",
                    "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready')",
                ],
                check=False,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("MODEL_GATEWAY_NOT_READY")
        run(
            [
                "docker",
                "cp",
                str(ROOT / "deploy/tests/model_gateway_probe.py"),
                "lifereel-servicesqa-interview-1:/tmp/model_gateway_probe.py",
            ]
        )
        probe = run([*compose, "exec", "-T", "interview", "python", "/tmp/model_gateway_probe.py"])
        result = {"status": "passed", **json.loads(probe.stdout.strip())}
    except Exception as exc:
        result["error"] = str(exc)
        raise
    finally:
        if created:
            run([*compose, "up", "-d", "--no-deps", "model-gateway"], check=False)
            run(["docker", "rm", "-f", name], check=False)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

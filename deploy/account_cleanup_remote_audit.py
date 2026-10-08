"""Stream the read-only auditor through the explicitly authorized SSH helper."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = "/opt/LifeReel-Biography"


def read_remote(client, command):
    _, stdout, stderr = client.exec_command(command, timeout=30)
    result = stdout.read().decode()
    stderr.read()  # Do not forward remote exceptions, environment or connection URLs.
    if stdout.channel.recv_exit_status():
        raise RuntimeError("REMOTE_READ_FAILED")
    return result.strip()


def collect(client, expected_sha):
    sha = read_remote(client, f"git -C {shlex.quote(REMOTE_ROOT)} rev-parse HEAD")
    if sha != expected_sha:
        raise RuntimeError("REMOTE_COMMIT_CHANGED_REVIEW_REQUIRED")
    status = read_remote(client, f"git -C {shlex.quote(REMOTE_ROOT)} status --porcelain")
    if status:
        raise RuntimeError("REMOTE_CHECKOUT_CHANGED_REVIEW_REQUIRED")
    containers = read_remote(
        client,
        "docker ps --filter label=com.docker.compose.project="
        "lifereel-production --format '{{.Names}} {{.Status}}'",
    )
    identity = read_remote(
        client,
        "docker ps --filter label=com.docker.compose.project="
        "lifereel-production --filter label=com.docker.compose.service="
        "identity --format '{{.Names}}'",
    ).splitlines()
    if len(identity) != 1:
        raise RuntimeError("IDENTITY_CONTAINER_NOT_UNIQUE")
    source = (ROOT / "deploy/account_cleanup_audit.py").read_text(encoding="utf-8")
    command = (
        f"docker exec -i -e PYTHONDONTWRITEBYTECODE=1 {shlex.quote(identity[0])} "
        "python - --with-storage --with-cache"
    )
    stdin, stdout, stderr = client.exec_command(command, timeout=300)
    stdin.write(source)
    stdin.flush()
    stdin.channel.shutdown_write()
    result = stdout.read().decode()
    stderr.read()
    if stdout.channel.recv_exit_status():
        raise RuntimeError("REMOTE_AUDIT_FAILED_DETAILS_REDACTED")
    report = json.loads(result)
    report["server"] = {
        "sha": sha,
        "checkout_clean": True,
        "containers": containers.splitlines(),
        "source_transport": "stdin_only",
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Local ignored tmp/ path for runtime evidence; never commit it",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    allowed = (ROOT / "tmp").resolve()
    if not output.is_relative_to(allowed):
        parser.error("Evidence must be saved inside the repository's ignored tmp/ directory")
    helper = ROOT / "tmp/plan-audits/release/server_access.py"
    spec = importlib.util.spec_from_file_location("authorized_server_access", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = module.connect()
    try:
        report = collect(client, args.expected_sha)
    finally:
        client.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=True)
    print(
        json.dumps(
            {
                "mode": "read_only",
                "sha": report["server"]["sha"],
                "account": report["account"],
                "ownership": report["ownership"],
                "blocker_counts": dict(Counter(item["code"] for item in report["blockers"])),
                "evidence_path": str(output),
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

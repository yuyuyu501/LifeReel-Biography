"""D4 release stages, run by an administrator on the documented production checkout."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from dotenv import set_key

ROOT = Path("/opt/LifeReel-Biography")
RELEASE_NAME = "d4-baseline-20261014"
BACKUP = Path("/opt/lifereel-backups") / RELEASE_NAME
RECORD = Path("/opt/lifereel-deploy") / RELEASE_NAME
COMPOSE = ["docker", "compose", "-f", "compose.production.yaml"]
MODULES = {
    **{
        f"lifereel_api.modules.interview.{name}": (
            f"services/interview/src/lifereel_api/modules/interview/{name}.py"
        )
        for name in (
            "d4", "grounding", "retrieval", "quality", "companion",
            "profile_extraction", "profile_service",
        )
    },
    **{
        f"lifereel_api.providers.{name}": (
            f"services/model-gateway/src/lifereel_api/providers/{name}.py"
        )
        for name in ("internal", "openai_compatible")
    },
    "lifereel_api.core.config": "apps/api/src/lifereel_api/core/config.py",
    "lifereel_api.core.errors": "apps/api/src/lifereel_api/core/errors.py",
    "lifereel_api.providers.rpc": "services/model-gateway/src/lifereel_api/providers/rpc.py",
    "lifereel_api.modules.book.writing": "services/book/src/lifereel_api/modules/book/writing.py",
    "lifereel_api.modules.book.service": "services/book/src/lifereel_api/modules/book/service.py",
    "lifereel_api.modules.book.profile_sources": (
        "services/book/src/lifereel_api/modules/book/profile_sources.py"
    ),
    "lifereel_api.modules.book.schemas": "services/book/src/lifereel_api/modules/book/schemas.py",
}


def out(*command):
    return subprocess.check_output(command, text=True).strip()


def run(*command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def no_jobs():
    for query in (
        "SELECT count(*) FROM tasks.jobs WHERE status IN ('queued','running')",
        "SELECT count(*) FROM interview.interview_voice_calls "
        "WHERE status IN ('connecting','active','closing')",
    ):
        assert (
            out(
                *COMPOSE,
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "lifereel",
                "-d",
                "lifereel",
                "-Atc",
                query,
            )
            == "0"
        ), "Active work exists"


def backup_database(name):
    path = BACKUP / name
    with path.open("wb") as stream:
        run(
            *COMPOSE,
            "exec",
            "-T",
            "postgres",
            "pg_dump",
            "-U",
            "lifereel",
            "-d",
            "lifereel",
            "-Fc",
            stdout=stream,
        )
    assert path.stat().st_size > 1000
    with path.open("rb") as stream:
        listing = run(
            *COMPOSE,
            "exec",
            "-T",
            "postgres",
            "pg_restore",
            "--list",
            stdin=stream,
            capture_output=True,
        )
    assert b"alembic_version" in listing.stdout
    path.with_suffix(".sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest())


def containers():
    return json.loads(out("docker", "inspect", *out(*COMPOSE, "ps", "-q").split()))


def prepare():
    no_jobs()
    assert shutil.disk_usage(ROOT).free > 8 * 1024**3
    BACKUP.mkdir(mode=0o700)
    RECORD.mkdir(mode=0o700, exist_ok=True)
    shutil.copy2(ROOT / ".env", BACKUP / "environment.before")
    backup_database("database.before.dump")
    images = []
    for item in containers():
        service = item["Config"]["Labels"]["com.docker.compose.service"]
        tag = f"lifereel/rollback-{service}:{RELEASE_NAME}"
        run("docker", "tag", item["Image"], tag)
        images.append(
            {
                "service": service,
                "image": item["Image"],
                "original_tag": item["Config"]["Image"],
                "retained_tag": tag,
            }
        )
    previous = out("git", "rev-parse", "HEAD")
    (BACKUP / "rollback.json").write_text(
        json.dumps({"commit": previous, "images": images}, indent=2)
    )
    run(
        "docker",
        "tag",
        f"lifereel/backend-runtime:{previous}",
        f"lifereel/d4-dependency-seed:{RELEASE_NAME}",
    )
    print(json.dumps({"backup": str(BACKUP), "previous": previous, "retained_images": len(images)}))


def build(release):
    previous = json.loads((BACKUP / "rollback.json").read_text())["commit"]
    assert not out(
        "git", "diff", previous, release, "--", "apps/api/requirements.lock", "apps/api/uv.lock"
    ), "Dependencies changed"
    dockerfile = RECORD / "Dockerfile.backend"
    dockerfile.write_text(f"""FROM lifereel/d4-dependency-seed:{RELEASE_NAME}
ARG RELEASE
LABEL org.opencontainers.image.revision=$RELEASE
WORKDIR /workspace
COPY apps/api/pyproject.toml apps/api/README.md apps/api/
COPY apps/api/src apps/api/src
COPY services services
RUN pip install --no-deps ./apps/api
COPY apps/api/alembic apps/api/alembic
COPY apps/api/alembic.ini apps/api/alembic.ini
WORKDIR /workspace/apps/api
""")
    override = RECORD / "build.override.yaml"
    override.write_text(f"""services:
  migrate:
    build:
      dockerfile: {dockerfile}
      args:
        RELEASE: {release}
  web:
    build:
      labels:
        org.opencontainers.image.revision: {release}
  gateway:
    build:
      labels:
        org.opencontainers.image.revision: {release}
""")
    os.environ["LIFEREEL_RELEASE"] = release
    run(*COMPOSE, "-f", str(override), "config", "--quiet")
    with (RECORD / "build.log").open("wb") as stream:
        run(*COMPOSE, "-f", str(override), "build", stdout=stream, stderr=stream)
    print(json.dumps({"built": release}))


def deploy(release, script_model=None):
    no_jobs()
    services = [
        s
        for s in out(*COMPOSE, "config", "--services").split()
        if s not in {"postgres", "redis", "migrate"}
    ]
    run(*COMPOSE, "stop", *services, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        no_jobs()
        backup_database("database.quiesced.dump")
        changes = {
            "LIFEREEL_RELEASE": release,
            "INTERVIEW_D4_ENHANCEMENT": "baseline",
        }
        if script_model:
            changes["SCRIPT_LLM_MODEL"] = script_model
        for key, value in changes.items():
            set_key(str(ROOT / ".env"), key, value)
        os.chmod(ROOT / ".env", 0o600)
        run(*COMPOSE, "config", "--quiet")
        with (RECORD / "migration.log").open("wb") as stream:
            run(*COMPOSE, "run", "--rm", "--no-deps", "migrate", stdout=stream, stderr=stream)
        with (RECORD / "start.log").open("wb") as stream:
            run(
                *COMPOSE,
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--wait",
                "--wait-timeout",
                "240",
                stdout=stream,
                stderr=stream,
            )
    except Exception:
        shutil.copy2(BACKUP / "environment.before", ROOT / ".env")
        with (RECORD / "rollback.log").open("wb") as stream:
            run(
                *COMPOSE,
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--wait",
                "--wait-timeout",
                "240",
                stdout=stream,
                stderr=stream,
            )
        raise
    shutil.copy2(ROOT / ".env", BACKUP / "environment.deployed")
    print(json.dumps({"deployed": release, "backup": str(BACKUP)}))


def verify(release, script_model=None):
    runtime = []
    for item in containers():
        service = item["Config"]["Labels"]["com.docker.compose.service"]
        assert item["State"]["Status"] == "running"
        assert item["State"].get("Health", {}).get("Status") == "healthy"
        if service not in {"postgres", "redis"}:
            assert item["Config"]["Image"].endswith(":" + release)
        runtime.append(
            {
                "service": service,
                "image": item["Image"],
                "tag": item["Config"]["Image"],
                "started": item["State"]["StartedAt"],
            }
        )
    assert len(runtime) == 16
    migration = out(
        *COMPOSE,
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "lifereel",
        "-d",
        "lifereel",
        "-Atc",
        "SELECT version_num FROM public.alembic_version",
    )
    assert migration == "20261012_0045"
    expected = {m: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for m, p in MODULES.items()}
    code = (
        "import importlib,inspect,hashlib,json; from pathlib import Path; ms="
        + repr(list(MODULES))
        + "; print(json.dumps({m:hashlib.sha256("
        "Path(inspect.getfile(importlib.import_module(m))).read_bytes()).hexdigest() for m in ms}))"
    )
    script_models = {}
    for service in ("interview", "worker-interview", "model-gateway", "book", "worker-book"):
        assert json.loads(out(*COMPOSE, "exec", "-T", service, "python", "-c", code)) == expected, (
            service
        )
        config = (
            "import json; from lifereel_api.core.config import get_settings; s=get_settings(); "
            "print(json.dumps([s.interview_recording_method,s.model_for('interview'),"
            "s.model_for('interview_review'),s.interview_review_enabled,"
            "s.interview_d4_enhancement]))"
        )
        assert json.loads(out(*COMPOSE, "exec", "-T", service, "python", "-c", config)) == [
            "d4",
            "doubao-seed-2-1-lite-260915",
            "gpt-6.1-sol",
            True,
            "baseline",
        ]
        script_config = (
            "import json; from lifereel_api.core.config import get_settings; "
            "print(json.dumps(get_settings().model_for('script')))"
        )
        actual_model = json.loads(
            out(*COMPOSE, "exec", "-T", service, "python", "-c", script_config)
        )
        script_models[service] = actual_model
        if script_model:
            assert actual_model == script_model, (service, actual_model)
    health = json.loads(out("curl", "-fsS", "https://bianjiaigc.com/health"))
    assert health["status"] == "ok"
    run("curl", "-fsS", "https://bianjiaigc.com/ready", stdout=subprocess.DEVNULL)
    run("curl", "-fsS", "https://bianjiaigc.com/system-status", stdout=subprocess.DEVNULL)
    (RECORD / "verification.json").write_text(
        json.dumps(
            {
                "release": release,
                "migration": migration,
                "runtime": runtime,
                "source_hashes": expected,
                "health": health,
                "enhancement": "baseline",
                "script_models": script_models,
                "backup": str(BACKUP),
            },
            indent=2,
        )
    )
    print(
        json.dumps(
            {
                "release": release,
                "healthy_services": len(runtime),
                "migration": migration,
                "runtime_hashes_verified": True,
                "recording_method": "d4",
                "enhancement": "baseline",
            }
        )
    )


def main():
    global RELEASE_NAME, BACKUP, RECORD
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "build", "deploy", "verify"])
    parser.add_argument("release", nargs="?")
    parser.add_argument("--release-name", default=RELEASE_NAME)
    parser.add_argument("--script-model", choices=["gpt-6.1-sol"])
    args = parser.parse_args()
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", args.release_name), "Invalid release name"
    RELEASE_NAME = args.release_name
    BACKUP = Path("/opt/lifereel-backups") / RELEASE_NAME
    RECORD = Path("/opt/lifereel-deploy") / RELEASE_NAME
    os.umask(0o077)
    os.chdir(ROOT)
    assert not out("git", "status", "--porcelain"), "Unexpected server changes"
    if args.stage == "prepare":
        prepare()
    else:
        assert args.release and re.fullmatch(r"[0-9a-f]{40}", args.release)
        assert out("git", "rev-parse", "HEAD") == args.release
        if args.stage == "build":
            build(args.release)
        elif args.stage == "deploy":
            deploy(args.release, args.script_model)
        else:
            verify(args.release, args.script_model)


if __name__ == "__main__":
    main()

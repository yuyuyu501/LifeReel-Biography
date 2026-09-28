"""Validate production connection configuration without contacting any services."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def test_prepare_env_preserves_special_characters_in_database_password(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "prepare_env", ROOT / "deploy" / "prepare_env.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    password = "test-only\\@:/?#%+2026"
    monkeypatch.setattr(module.secrets, "token_hex", lambda _: password)
    source = tmp_path / "source.env"
    target = tmp_path / "production.env"
    required = (
        "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_BUCKET", "S3_ENDPOINT_URL",
        "OPENAI_COMPATIBLE_API_KEY", "OPENAI_COMPATIBLE_BASE_URL",
        "VOLCENGINE_API_KEY", "BOOTSTRAP_OWNER_EMAIL", "BOOTSTRAP_OWNER_PASSWORD",
    )
    source.write_text("\n".join(f"{key}=isolated-test" for key in required), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["prepare_env", "--source", str(source),
                                       "--target", str(target)])
    module.main()
    values = dotenv_values(target)
    url = make_url(values["DATABASE_URL"])
    assert values["POSTGRES_PASSWORD"] == password
    assert url.password == password
    assert (url.host, url.port, url.database) == ("postgres", 5432, "lifereel")
    assert values["POSTGRES_BIND_HOST"] == "127.0.0.1"
    assert values["POSTGRES_PORT"] == "5432"


@pytest.mark.parametrize("bind_host,published_port", [("127.0.0.1", 5432), ("0.0.0.0", 15432)])
def test_compose_uses_encoded_url_and_configurable_port(tmp_path, bind_host, published_port):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker Compose CLI is required for configuration validation")
    password = "test-only\\@:/?#%+2026"
    database_url = f"postgresql+psycopg://lifereel:{quote(password, safe='')}@postgres:5432/lifereel"
    # Never load the real project environment or print the rendered configuration.
    compose = tmp_path / "compose.yaml"
    compose.write_text((ROOT / "compose.production.yaml").read_text(encoding="utf-8"),
                       encoding="utf-8")
    (tmp_path / ".env").write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        POSTGRES_PASSWORD=password, DATABASE_URL=database_url, API_ACCESS_KEY="isolated-test",
        POSTGRES_BIND_HOST=bind_host, POSTGRES_PORT=str(published_port),
    )
    result = subprocess.run(
        [docker, "compose", "--env-file", str(tmp_path / ".env"),
         "-f", str(compose), "config", "--format", "json"],
        env=env, capture_output=True, text=True, timeout=30, check=True,
    )
    services = json.loads(result.stdout)["services"]
    assert services["postgres"]["environment"]["POSTGRES_PASSWORD"] == password
    assert services["api"]["environment"]["DATABASE_URL"] == database_url
    port = services["postgres"]["ports"][0]
    assert port["host_ip"] == bind_host
    assert int(port["published"]) == published_port
    assert port["target"] == 5432


def test_alembic_accepts_percent_encoded_database_password():
    password = "test-only\\@:/?#%+2026"
    env = os.environ.copy()
    env.update(
        APP_ENV="test",
        DATABASE_URL=(
            f"postgresql+psycopg://lifereel:{quote(password, safe='')}@localhost:5432/isolated_test"
        ),
        LLM_PROVIDER="mock", ASR_PROVIDER="mock", VIDEO_PROVIDER="mock",
        IMAGE_PROVIDER="mock", VOICE_PROVIDER="mock", REALTIME_VOICE_PROVIDER="disabled",
        PHOTO_RESTORATION_PROVIDER="inherit", STORAGE_BACKEND="local",
        AUTO_CREATE_SCHEMA="false", SMS_ENABLED="false",
    )
    # SQL-only mode exercises the actual env.py without opening a DB connection.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade",
         "20260923_0032:20260924_0033", "--sql"],
        cwd=ROOT / "apps" / "api", env=env, capture_output=True,
        text=True, timeout=30, check=True,
    )
    assert "CREATE TABLE platform_identities" in result.stdout
    assert "CREATE TABLE mini_sessions" in result.stdout

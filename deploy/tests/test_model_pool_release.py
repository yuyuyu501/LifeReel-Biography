"""Release environment changes are opt-in and retain the rollback environment."""

import importlib.util
import subprocess
from pathlib import Path

import pytest
from dotenv import dotenv_values


@pytest.fixture
def release(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "d4_baseline_release.py"
    spec = importlib.util.spec_from_file_location("model_pool_release_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root, backup, record = (tmp_path / name for name in ("root", "backup", "record"))
    for directory in (root, backup, record):
        directory.mkdir()
    before = "INTERVIEW_LLM_MODEL=old-model\nSCRIPT_LLM_MODEL=old-script\nPRIVATE_KEY=synthetic\n"
    (root / ".env").write_text(before)
    (backup / "environment.before").write_text(before)
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "BACKUP", backup)
    monkeypatch.setattr(module, "RECORD", record)
    monkeypatch.setattr(module, "no_jobs", lambda: None)
    monkeypatch.setattr(module, "backup_database", lambda _: None)
    monkeypatch.setattr(module, "out", lambda *args: "postgres redis migrate book interview")
    monkeypatch.setattr(module, "run", lambda *args, **kwargs: None)
    return module, before


@pytest.mark.parametrize("enabled", [True, False])
def test_pool_release_only_changes_model_routing_when_enabled(release, enabled):
    module, _ = release
    module.deploy("a" * 40, model_pools=enabled)
    env = dotenv_values(module.ROOT / ".env")
    assert env["LIFEREEL_RELEASE"] == "a" * 40
    assert env["PRIVATE_KEY"] == "synthetic"
    if enabled:
        assert env["INTERVIEW_LLM_MODEL"] == env["SCRIPT_LLM_MODEL"] == "gpt-6.1-sol"
        assert "lite" not in env["LLM_MODEL_POOL_INTERVIEW_REVIEW"]
        assert len(env["LLM_MODEL_POOL_INTERVIEW_REVIEW"].split(",")) == 2
        assert len(env["LLM_MODEL_POOL_SCRIPT"].split(",")) == 3
    else:
        assert env["INTERVIEW_LLM_MODEL"] == "old-model"
        assert env["SCRIPT_LLM_MODEL"] == "old-script"
        assert "LLM_MODEL_POOL_SCRIPT" not in env


def test_failed_pool_release_restores_exact_previous_environment(release, monkeypatch):
    module, before = release

    def run(*args, **kwargs):
        if "migrate" in args:
            raise subprocess.CalledProcessError(1, ["synthetic migration"])

    monkeypatch.setattr(module, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        module.deploy("a" * 40, model_pools=True)
    assert (module.ROOT / ".env").read_text() == before

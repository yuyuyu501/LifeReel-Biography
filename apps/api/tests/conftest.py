from __future__ import annotations

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="lifereel-tests-")
TEST_DB = Path(_TEST_DIRECTORY.name) / "test.db"
os.environ["APP_ENV"] = "test"
os.environ["REGISTRATION_ENABLED"] = "false"
os.environ["SMS_ENABLED"] = "false"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["AUTO_CREATE_SCHEMA"] = "true"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["ASR_PROVIDER"] = "mock"
os.environ["IMAGE_PROVIDER"] = "mock"
os.environ["PHOTO_REDRAW_PROVIDER"] = "disabled"
os.environ["PHOTO_RESTORATION_PROVIDER"] = "inherit"
os.environ["VIDEO_REFERENCE_STYLE"] = "original"
os.environ["SILICONFLOW_API_KEY"] = ""
os.environ["VIDEO_PROVIDER"] = "mock"
os.environ["VOICE_PROVIDER"] = "mock"
os.environ["REALTIME_VOICE_PROVIDER"] = "disabled"
os.environ["DOUBAO_REALTIME_API_KEY"] = ""
os.environ["MANUAL_WECHAT_ENABLED"] = "false"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["OSS_DIRECT_UPLOAD_ENABLED"] = "false"
os.environ["BILLING_TEXT_MODE"] = "per_successful_chapter_update"
os.environ["BILLING_VIDEO_MODE"] = "per_second"

from lifereel_api.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from lifereel_api.core.database import Base, engine  # noqa: E402
from lifereel_api.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def legacy_pricing(monkeypatch):
    # Existing lifecycle regressions deliberately exercise the original tariff.
    # test_standard_pricing overrides it to verify the new production catalogue.
    monkeypatch.setattr(get_settings(), "billing_script_chapter_cents", 2)
    monkeypatch.setattr(get_settings(), "billing_video_cents_per_second", 20)
    monkeypatch.setattr(get_settings(), "billing_price_version", "trial-2026-09-per-update")


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def pytest_sessionfinish() -> None:
    engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()
    _TEST_DIRECTORY.cleanup()

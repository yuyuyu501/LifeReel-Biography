import json

import pytest

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.memory.service import _extract_claim
from lifereel_api.modules.memory.structured import MemoryClient


@pytest.mark.parametrize("provider", ["mock", "openai-compatible"])
def test_oversized_memory_source_rejected_without_model_call(monkeypatch, provider):
    monkeypatch.setattr(get_settings(), "llm_provider", provider)
    monkeypatch.setattr(MemoryClient, "chat_json", lambda *args: pytest.fail("paid call"))
    with pytest.raises(ApiError) as error:
        _extract_claim("回忆" * 10_000 + "末尾", "document_text")
    assert error.value.status_code == 413
    assert error.value.code == ErrorCode.MEMORY_INPUT_TOO_LARGE
    assert error.value.context["coverage"] == "none"


def test_memory_source_at_limit_reaches_model_including_tail(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openai-compatible")
    monkeypatch.setattr(settings, "openai_compatible_base_url", "https://model.example/v1")
    monkeypatch.setattr(settings, "openai_compatible_api_key", "test-only")
    monkeypatch.setattr(settings, "memory_llm_model", "test")
    original = "回" * 19_996 + "末尾事实"
    observed = []

    def answer(self, system, user):
        observed.append(json.loads(user)["source_text"])
        return {"claim_text": "末尾事实", "claim_type": "recollection", "confidence": 1.0}

    monkeypatch.setattr(MemoryClient, "chat_json", answer)
    assert _extract_claim(original, "document_text")[0] == "末尾事实"
    assert observed == [original]

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.interview.chapter_prompts import get_chapter_prompt_profile
from lifereel_api.modules.script.schemas import ScriptGenerateRequest
from lifereel_api.modules.script.service import _llm_scenes
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


@pytest.mark.parametrize("duration", [15, 18, 23, 30, 14, 31, None, True, "20"])
def test_script_duration_is_ai_chosen_and_must_be_in_range(monkeypatch, duration):
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_compatible_base_url", "https://synthetic.test")
    monkeypatch.setattr(settings, "openai_compatible_api_key", "synthetic")
    monkeypatch.setattr(settings, "script_llm_model", "synthetic")
    claim = SimpleNamespace(id=uuid4(), claim_text="Childhood", source_quote="Childhood",
                            confidence=1, review_status="unreviewed")

    def respond(self, system, user):
        assert "不要每次都写30秒" in system
        assert json.loads(user)["duration_range_seconds"] == {"min": 15, "max": 30}
        return {"chapter": {
            "heading": "Chapter", "narration": "A short memory.", "visual_prompt": "A home.",
            "duration_seconds": duration, "source_claim_ids": [str(claim.id)],
            "shots": [{"visual_prompt": "Home", "duration_seconds": 6,
                       "source_claim_ids": [str(claim.id)]}],
        }}

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", respond)
    args = (
        SimpleNamespace(preferred_name=None, display_name="Test"),
        ScriptGenerateRequest(subject_id=uuid4()), [claim], get_chapter_prompt_profile(None),
    )
    if type(duration) is int and 15 <= duration <= 30:
        _, scenes, _ = _llm_scenes(*args)
        assert scenes[0]["duration_seconds"] == duration
        assert sum(s["duration_seconds"] for s in scenes[0]["shots"]) == duration
    else:
        with pytest.raises(ApiError) as exc:
            _llm_scenes(*args)
        assert exc.value.code == ErrorCode.SCRIPT_LLM_RESPONSE_INVALID

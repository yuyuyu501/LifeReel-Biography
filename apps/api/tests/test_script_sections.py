from types import SimpleNamespace
from uuid import uuid4

import pytest

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.interview.chapter_prompts import get_chapter_prompt_profile
from lifereel_api.modules.script.schemas import ScriptGenerateRequest
from lifereel_api.modules.script.service import _llm_scenes
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


@pytest.fixture
def generate_sections(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_compatible_base_url", "https://synthetic.test")
    monkeypatch.setattr(settings, "openai_compatible_api_key", "synthetic")
    monkeypatch.setattr(settings, "script_llm_model", "synthetic")
    claim = SimpleNamespace(id=uuid4(), claim_text="A return home", source_quote="Welcome home.",
                            confidence=1, review_status="unreviewed")
    chapter = {
        "heading": "Home", "plot": "A return home and reunion.",
        "dialogues": [
            {"kind": "narration", "speaker": "Subject", "text": "I returned home."},
            {"kind": "dialogue", "speaker": "Mother", "text": "Welcome home."},
        ],
        "visual_prompt": "A small home in winter.", "duration_seconds": 20,
        "source_claim_ids": [str(claim.id)],
        "shots": [{"visual_prompt": "A door opens.", "duration_seconds": 20,
                   "source_claim_ids": [str(claim.id)]}],
    }

    def respond(self, system, user):
        assert "禁止编造对话" in system
        assert "不输出独立narration" in system
        return {"chapter": chapter}

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", respond)

    def generate():
        return _llm_scenes(
            SimpleNamespace(preferred_name=None, display_name="Subject"),
            ScriptGenerateRequest(subject_id=uuid4()), [claim], get_chapter_prompt_profile(None),
        )

    return chapter, generate


def test_four_part_script_derives_canonical_spoken_text(generate_sections):
    chapter, generate = generate_sections
    _, scenes, _ = generate()
    assert scenes[0]["plot"] == chapter["plot"]
    assert scenes[0]["dialogues"] == chapter["dialogues"]
    assert scenes[0]["narration"] == "I returned home.\nWelcome home."
    assert scenes[0]["shots"][0]["visual_prompt"] == "A door opens."


@pytest.mark.parametrize("field,value", [
    ("plot", None), ("plot", " "), ("plot", "a" * 4001),
    ("dialogues", []), ("dialogues", "text"),
    ("dialogues", [{"kind": "unknown", "speaker": "Subject", "text": "Hello"}]),
    ("dialogues", [{"kind": "narration", "speaker": " ", "text": "Hello"}]),
    ("dialogues", [{"kind": "narration", "speaker": "Subject", "text": " "}]),
])
def test_invalid_plot_or_dialogue_returns_structured_error(generate_sections, field, value):
    chapter, generate = generate_sections
    chapter[field] = value
    with pytest.raises(ApiError) as exc:
        generate()
    assert exc.value.code == ErrorCode.SCRIPT_LLM_RESPONSE_INVALID

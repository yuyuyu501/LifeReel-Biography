from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.processing_limits import ProcessingLimits
from lifereel_api.modules.identity.models import Person
from lifereel_api.modules.interview.chapter_prompts import get_chapter_prompt_profile
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.modules.script import service
from lifereel_api.modules.script.schemas import ScriptGenerateRequest, ScriptSceneUpdate
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


def _claim(text="I remember home."):
    return SimpleNamespace(id=uuid4(), claim_text=text, source_quote=text,
                           confidence=1, review_status="unreviewed")


def test_mock_dialogue_accepts_exact_boundary_and_rejects_overflow_without_truncating():
    claim = _claim("字" * 1999)
    scene = service._rule_scenes("Subject", [claim])[0]
    assert scene["dialogues"][0]["text"] == "字" * 1999 + "。"
    ScriptSceneUpdate.model_validate({
        "expected_version": 1,
        **{key: scene[key] for key in (
            "heading", "plot", "dialogues", "visual_prompt", "duration_seconds",
        )},
        "shots": [{key: shot[key] for key in ("shot_type", "visual_prompt", "duration_seconds")}
                  for shot in scene["shots"]],
    })
    with pytest.raises(ApiError) as exc:
        service._rule_scenes("Subject", [_claim("字" * 2000)])
    assert exc.value.status_code == 413
    assert exc.value.code == ErrorCode.SCRIPT_MOCK_OUTPUT_TOO_LARGE
    assert exc.value.context["stage"] == "script_mock_output"


def _configured_provider(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_compatible_base_url", "https://synthetic.test")
    monkeypatch.setattr(settings, "openai_compatible_api_key", "synthetic")
    monkeypatch.setattr(settings, "script_llm_model", "synthetic")


@pytest.mark.parametrize("oversized", [
    "claim", "source_quote", "current_script", "instructions", "aggregate", "json_escape",
])
def test_full_script_request_budget_blocks_provider_call(monkeypatch, oversized):
    _configured_provider(monkeypatch)
    monkeypatch.setattr(service, "get_processing_limits", lambda: ProcessingLimits(
        script_input_max_chars=4000,
    ))
    monkeypatch.setattr(OpenAICompatibleClient, "chat_json",
                        lambda *args: pytest.fail("over-budget request reached provider"))
    claim = _claim()
    brief = {}
    large = "私密材料" * 2000
    if oversized == "claim":
        claim.claim_text = large
    elif oversized == "source_quote":
        claim.source_quote = large
    elif oversized == "current_script":
        brief["current_script"] = {"narration": large}
    elif oversized == "aggregate":
        claim.claim_text = "字" * 2100
        claim.source_quote = "字" * 2100
    elif oversized == "json_escape":
        claim.claim_text = "\x00" * 1000
    else:
        brief["script_instructions"] = large
    with pytest.raises(ApiError) as exc:
        service._llm_scenes(
            SimpleNamespace(display_name="Subject", preferred_name=None),
            ScriptGenerateRequest(subject_id=uuid4()), [claim], get_chapter_prompt_profile(None),
            brief,
        )
    assert exc.value.status_code == 413
    assert exc.value.code == ErrorCode.SCRIPT_INPUT_TOO_LARGE
    assert exc.value.context["stage"] == "script_input"


@pytest.mark.parametrize("invalid", ["visual", "heading", "shot_visual", "shot_type",
                                     "shot_duration", "dialogue", "title", "references"])
def test_provider_output_schema_is_enforced_before_persistence(monkeypatch, caplog, invalid):
    _configured_provider(monkeypatch)
    claim = _claim()
    chapter = service._rule_scenes("Subject", [claim])[0]
    result = {"chapter": deepcopy(chapter)}
    chapter = result["chapter"]
    sentinel = "PRIVATE_DOCUMENT_SENTINEL"
    if invalid == "visual":
        chapter["visual_prompt"] = sentinel * 200
    elif invalid == "heading":
        chapter["heading"] = sentinel * 20
    elif invalid == "shot_visual":
        chapter["shots"][0]["visual_prompt"] = sentinel * 200
    elif invalid == "shot_type":
        chapter["shots"][0]["shot_type"] = sentinel
    elif invalid == "shot_duration":
        chapter["shots"][0]["duration_seconds"] = True
    elif invalid == "dialogue":
        chapter["dialogues"][0]["text"] = sentinel * 100
    elif invalid == "title":
        result["title"] = sentinel * 20
    else:
        chapter["source_claim_ids"] = [str(uuid4())]
    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", lambda *args: result)
    with pytest.raises(ApiError) as exc:
        service._llm_scenes(
            SimpleNamespace(display_name="Subject", preferred_name=None),
            ScriptGenerateRequest(subject_id=uuid4()), [claim], get_chapter_prompt_profile(None),
        )
    assert exc.value.code == ErrorCode.SCRIPT_LLM_RESPONSE_INVALID
    assert sentinel not in caplog.text


def _saved_script(client):
    person = client.post("/v1/persons", json={"display_name": "Workspace boundary"}).json()
    interview = client.post("/v1/interviews", json={"subject_id": person["id"]}).json()
    with SessionLocal() as db:
        subject = db.get(Person, UUID(person["id"]))
        db.add(MemoryClaim(tenant_id=subject.tenant_id, subject_id=subject.id,
                           claim_text="I remember home.", source_quote="I remember home.",
                           claim_type="recollection", confidence=1))
        db.commit()
    generated = client.post("/v1/scripts/generate", json={"subject_id": person["id"]})
    assert generated.status_code == 201
    saved = client.get(f"/v1/scripts/{generated.json()['id']}")
    assert saved.status_code == 200
    return person, interview, saved.json()


@pytest.mark.parametrize("failure", ["legacy_input", "mock_overflow", "invalid_output"])
def test_rejected_generation_preserves_saved_script_and_readable_workspace(client, monkeypatch,
                                                                          failure):
    person, interview, saved = _saved_script(client)
    if failure == "invalid_output":
        generate = service._rule_scenes

        def invalid(*args):
            scenes = generate(*args)
            scenes[0]["dialogues"][0]["text"] = "x" * 2001
            return scenes

        monkeypatch.setattr(service, "_rule_scenes", invalid)
        expected_status = 502
    else:
        with SessionLocal() as db:
            claim = db.scalar(select(MemoryClaim))
            claim.claim_text = "x" * (50_000 if failure == "legacy_input" else 2100)
            claim.source_quote = claim.claim_text
            db.commit()
        expected_status = 413
    rejected = client.post("/v1/scripts/generate", json={"subject_id": person["id"]})
    assert rejected.status_code == expected_status
    current = client.get(f"/v1/scripts/{saved['id']}")
    assert current.status_code == 200
    assert current.json() == saved
    workspace = client.get(f"/v1/interviews/{interview['id']}/workspace")
    assert workspace.status_code == 200
    assert workspace.json()["script"]["scenes"] == saved["scenes"]


def test_all_accepted_claims_are_used_instead_of_silently_dropping_after_forty(client):
    person, _, saved = _saved_script(client)
    with SessionLocal() as db:
        subject = db.get(Person, UUID(person["id"]))
        for index in range(41):
            db.add(MemoryClaim(tenant_id=subject.tenant_id, subject_id=subject.id,
                               claim_text=f"Memory {index}", source_quote=f"Memory {index}",
                               claim_type="recollection", confidence=1))
        db.commit()
        expected_ids = {str(claim.id) for claim in db.scalars(select(MemoryClaim))}
    generated = client.post("/v1/scripts/generate", json={"subject_id": person["id"]})
    assert generated.status_code == 201
    assert generated.json()["id"] == saved["id"]
    assert set(generated.json()["scenes"][0]["source_claim_ids"]) == expected_ids
    assert "Memory 40" in generated.json()["scenes"][0]["narration"]

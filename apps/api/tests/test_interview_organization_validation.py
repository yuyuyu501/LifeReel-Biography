"""Additional frozen validation contracts; mocked providers, no claim of model accuracy."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from lifereel_api.modules.book import profile_sources
from lifereel_api.modules.interview import organization, profile_service
from lifereel_api.modules.interview.profile_extraction import process
from lifereel_api.modules.interview.profile_schemas import ProfilePatch
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient
from test_interview_d4 import draft, enabled  # noqa: F401
from test_interview_organization_persistence import create

from lifereel_api.core.database import SessionLocal


@pytest.mark.parametrize("state,certainty,expected", [
    ("deferred", "reported", "deferred"),
    ("not_applicable", "reported", "not_applicable"),
    ("filled", "uncertain", "uncertain"),
    ("empty", "reported", "missing"),
])
def test_additional_coverage_boundaries(state, certainty, expected):
    entry = {
        "id": str(uuid4()), "field_key": "work.meaning", "state": state,
        "certainty": certainty, "record_key": "single", "use_scope": "internal",
    }
    result = organization.context([entry], [])
    field = next(f for f in result["coverage"] if f["field_key"] == entry["field_key"])
    assert field["states"] == [expected]
    assert result["events"] == []


@pytest.mark.parametrize("edited", [False, True])
def test_checkpoint_reuse_or_invalidation_after_manual_edit(
    client, enabled, monkeypatch, edited,  # noqa: F811
):
    profile_id = create(client)
    calls = []

    def structured(self, prompt, value, schema):
        calls.append(json.loads(value))
        return draft([], source=json.loads(value)["target_source"])

    monkeypatch.setattr(OpenAICompatibleClient, "chat_structured", structured)
    with SessionLocal() as db:
        profile = profile_service.read(db, enabled.default_tenant_id, profile_id)
        checkpoint = {
            "output": {
                "changes": [{"field_key": "identity.birth_time", "value": "1970年",
                             "quote": "我1970年出生。"}],
                "next_question": "您想聊童年吗？",
            },
            "entry_versions": {e["id"]: e["version_number"] for e in profile["entries"]},
            "audit": {"verdict": "pass"},
        }
        if edited:
            profile_service.patch(db, enabled.default_tenant_id, profile_id, ProfilePatch(
                expected_version=profile["version_number"],
                changes=[{"field_key": "identity.birth_time", "value": "1971年"}],
            ))
        workflow = SimpleNamespace(session_id=uuid4(), profile_result={"extraction": checkpoint})
        result = process(
            db, enabled.default_tenant_id, profile_id, "我1970年出生。",
            {"type": "test", "id": "checkpoint-validation", "version": 1}, uuid4(), workflow,
        )
        birth = next(e for e in result["profile"]["entries"]
                     if e["field_key"] == "identity.birth_time")
        assert birth["value"] == ("1971年" if edited else "1970年")
        assert len(calls) == (2 if edited else 0)
        if edited:
            assert birth["source"]["type"] == "manual"


@pytest.mark.parametrize("scope", ["works", "internal"])
def test_book_material_does_not_promote_audit_quote_to_current_fact(monkeypatch, scope):
    entry_id, chapter_id, tenant, profile_id = map(str, [uuid4(), uuid4(), uuid4(), uuid4()])
    entry = {
        "id": entry_id, "field_key": "work.records[]", "state": "filled",
        "certainty": "reported", "use_scope": scope, "version_number": 3,
        "value": {"facts": [{"value": "1999年", "evidence": [
            {"quote": "之前误说1998年，现在更正为1999年。"},
        ]}]},
        "source": {"quote": "更正为1999年。"},
    }
    profile = {"id": profile_id, "version_number": 3, "entries": [entry]}
    chapter = SimpleNamespace(source_entry_ids=[entry_id], title="工作", archived=False)
    book = SimpleNamespace(
        id=uuid4(), tenant_id=tenant, profile_id=profile_id, directory_version=2, target_words=None,
    )
    monkeypatch.setattr(profile_sources, "profile_read", lambda *a, **k: profile)
    result = profile_sources.source(SimpleNamespace(scalar=lambda query: chapter), book, chapter_id)
    assert len(result["claims"]) == (1 if scope == "works" else 0)
    if scope == "works":
        text = result["claims"][0]["text"]
        assert "1999年" in text and "1998年" not in text and "evidence" not in text
    else:
        assert result["restricted_entry_ids"] == [entry_id]

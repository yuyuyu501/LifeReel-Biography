"""Synthetic end-to-end D4 organization saves; all model responses are mocked."""

import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from lifereel_api.modules.interview import organization, profile_service, quality
from lifereel_api.modules.interview.profile_extraction import process
from lifereel_api.modules.interview.profile_models import LifeProfileRevision
from lifereel_api.modules.interview.profile_schemas import ProfilePatch
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient
from sqlalchemy import select
from test_interview_d4 import draft, enabled, fact, material  # noqa: F401
from test_interview_organization import adapt, stored

from lifereel_api.core.database import SessionLocal


def create(client):
    person = client.post("/v1/persons", json={"display_name": "资料整理合成人物"}).json()
    session = client.post("/v1/interviews", json={"subject_id": person["id"]}).json()
    return UUID(session["profile_id"])


def test_multiturn_save_relink_supplement_correct_and_replay(client, enabled, monkeypatch):  # noqa: F811
    profile_id = create(client)
    calls = []

    def structured(self, prompt, value, schema):
        data = json.loads(value)
        assert organization.VERSION == data["organization"]["version"]
        assert organization.GUIDANCE in prompt
        calls.append((self.model, data["new_answer"]))
        sid, text = data["target_source"], data["new_answer"]
        entries = [e for e in data["current_entries"] if e["field_key"] == "work.records[]"]
        link = entries[0]["id"] if entries else None
        if text == "我1998年在图书馆入职。":
            rows = [
                fact(source=sid, predicate="employment_start", value="1998年",
                     quote=text, event_key="library", use_scope="internal"),
                fact(source=sid, predicate="workplace", value="图书馆",
                     quote=text, event_key="library", candidate_id="F2", use_scope="internal"),
            ]
        elif text == "对，就是图书馆那段。":
            rows = [fact(source=sid, predicate="workplace", value="图书馆", quote=text,
                         event_key="unstable-new-key", evidence=[
                             {"source_id": sid, "quote": text},
                             {"source_id": entries[0]["source_id"],
                              "quote": "我1998年在图书馆入职。"},
                         ])]
        elif text == "我2005年离职。":
            rows = [fact(source=sid, predicate="employment_end", value="2005年",
                         quote=text, entry_id=link, event_key="library")]
        else:
            rows = [fact(source=sid, predicate="employment_start", value="1999年",
                         quote=text, entry_id=link, event_key="library")]
        return draft(rows, source=sid)

    monkeypatch.setattr(OpenAICompatibleClient, "chat_structured", structured)
    texts = ["我1998年在图书馆入职。", "对，就是图书馆那段。", "我2005年离职。",
             "更正一下，我1999年入职。"]
    with SessionLocal() as db:
        for i, text in enumerate(texts):
            request = uuid4()
            source = {"type": "test", "id": f"turn-{i}", "version": 1}
            result = process(db, enabled.default_tenant_id, profile_id, text, source, request)
            assert result["audit"]["verdict"] == "pass", result["audit"]
            replay = process(db, enabled.default_tenant_id, profile_id, text, source, request)
            assert replay["profile"]["version_number"] == result["profile"]["version_number"]
        final = profile_service.read(db, enabled.default_tenant_id, profile_id)
        entries = [e for e in final["entries"] if e["field_key"] == "work.records[]"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["use_scope"] == "internal"
        assert {a["value"] for a in entry["value"]["facts"]} == {"图书馆", "2005年", "1999年"}
        assert all(a["evidence"] for a in entry["value"]["facts"])
        year = next(a for a in entry["value"]["facts"] if a["predicate"] == "employment_start")
        assert {e["id"] for e in year["evidence"]} == {"turn-3"}
        revisions = list(db.scalars(select(LifeProfileRevision).where(
            LifeProfileRevision.profile_id == profile_id, LifeProfileRevision.actor == "ai",
        )))
        assert len(revisions) == 4
        assert any("1998年" in str(r.changes) for r in revisions)
        claim = db.scalar(select(MemoryClaim).where(
            MemoryClaim.profile_entry_id == UUID(entry["id"]),
        ))
        assert "1999年" in claim.claim_text and "1998年" not in claim.claim_text
        assert '"evidence"' not in claim.claim_text and claim.review_status == "private"
    assert len(calls) == 8  # two existing stages per new turn, none for replay


@pytest.mark.parametrize("kind", ["different_actor", "negation", "uncertain", "refusal"])
def test_atomic_states_reach_database(client, enabled, monkeypatch, kind):  # noqa: F811
    cases = {
        "different_actor": ("父亲去了长沙。", dict(entity="father", predicate="moved_to",
                                              value="长沙"), "family.members[]", "filled"),
        "negation": ("我上过学校但没毕业。",
                     dict(predicate="learning_records", value="上过学校但没毕业"),
                     "learning.records[]", "filled"),
        "uncertain": ("我可能在1998年进厂。", dict(predicate="employment_start", value="1998年",
                                                status="uncertain"), "work.records[]", "filled"),
        "refusal": ("我欠过债，原因不讲。", dict(predicate="debt_cause", value="未披露",
                                             status="declined"), "turning.hardships[]", "declined"),
    }
    text, args, field, state = cases[kind]
    profile_id = create(client)

    def structured(self, prompt, value, schema):
        sid = json.loads(value)["target_source"]
        return draft([fact(source=sid, quote=text, **args)], source=sid)

    monkeypatch.setattr(OpenAICompatibleClient, "chat_structured", structured)
    with SessionLocal() as db:
        result = process(db, enabled.default_tenant_id, profile_id, text,
                         {"type": "test", "id": kind, "version": 1}, uuid4())
        assert result["audit"]["verdict"] == "pass"
        persisted = profile_service.read(db, enabled.default_tenant_id, profile_id)
        entry = next(e for e in persisted["entries"] if e["field_key"] == field)
        assert entry["state"] == state
        atom = entry["value"]["facts"][0]
        assert atom["entity_id"] == args.get("entity", "self")
        assert atom["value"] == args["value"] and atom["status"] == args.get("status", "reported")
        assert atom["evidence"][0]["id"] == kind


def test_manual_update_during_model_call_rejects_late_write(client, enabled, monkeypatch):  # noqa: F811
    from lifereel_api.core.errors import ApiError

    profile_id = create(client)
    modified = False

    def structured(self, prompt, value, schema):
        nonlocal modified
        sid = json.loads(value)["target_source"]
        if not modified:
            modified = True
            with SessionLocal() as editor:
                profile = profile_service.read(editor, enabled.default_tenant_id, profile_id)
                profile_service.patch(editor, enabled.default_tenant_id, profile_id, ProfilePatch(
                    expected_version=profile["version_number"],
                    changes=[{"field_key": "identity.birth_time", "value": "1971年"}],
                ))
        return draft([fact(source=sid)], source=sid)

    monkeypatch.setattr(OpenAICompatibleClient, "chat_structured", structured)
    request = uuid4()
    with SessionLocal() as db:
        with pytest.raises(ApiError) as error:
            process(db, enabled.default_tenant_id, profile_id, "我1970年出生。",
                    {"type": "test", "id": "late", "version": 1}, request)
        assert error.value.status_code == 409
        db.rollback()
        persisted = profile_service.read(db, enabled.default_tenant_id, profile_id)
        assert next(e for e in persisted["entries"]
                    if e["field_key"] == "identity.birth_time")["value"] == "1971年"
        assert db.scalar(select(LifeProfileRevision).where(
            LifeProfileRevision.request_id == request,
        )) is None


def test_catalog_uses_active_atom_sources_and_legacy_fallback():
    text = "更正，我1999年入职。"
    output, _ = adapt([fact(predicate="employment_start", value="1999年", quote=text)],
                      material(text))
    entry = stored(output["changes"][0], text)
    entry["source"]["evidence"] = [
        {"type": "test", "id": "obsolete", "version": 1, "quote": "我1998年入职。"},
    ]
    data = {**material("接着说。"), "current_entries": [entry]}
    catalog = quality.source_catalog(data)
    assert [e["quote"] for e in catalog[f"entry:{entry['id']}"]] == [text]
    before = deepcopy(entry)
    entry["value"]["facts"][0].pop("evidence")
    assert len(organization.active_evidence(entry)) == 2
    assert "evidence" in before["value"]["facts"][0]  # no mutation by catalog


def test_ambiguous_atoms_inside_one_record_are_not_automatically_linked():
    text = "我在图书馆工作。"
    initial, _ = adapt([fact(predicate="workplace", value="图书馆", quote=text)], material(text))
    entry = stored(initial["changes"][0], text)
    entry["value"]["facts"].append({
        **deepcopy(entry["value"]["facts"][0]), "event_key": "second-library-job",
    })
    output, trace = adapt([fact(predicate="workplace", value="图书馆", quote=text,
                                event_key="new")],
                          {**material(text), "current_entries": [entry]})
    assert output["changes"][0].get("id") is None and not trace.get("organized_links")

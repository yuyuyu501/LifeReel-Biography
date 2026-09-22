import copy
import json
from uuid import UUID

import pytest
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.memory import service
from lifereel_api.modules.memory.models import MemoryClaim, MemoryConflict, TimelineAnchor
from lifereel_api.modules.memory.structured import validate
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


def graph(old="old", new="new"):
    return {
        "entities": [],
        "timeline": [
            {"year": 1970, "time_text": "1970年", "event_text": "和母亲过桥",
             "precision": "year", "source_claim_id": old},
            {"year": 1971, "time_text": "1971年", "event_text": "和母亲过桥",
             "precision": "year", "source_claim_id": new},
            {"year": 1962, "time_text": "1962年", "event_text": "出生",
             "precision": "year", "source_claim_id": old},
        ],
        "conflicts": [
            {"conflict_key": "bridge_year", "description": "过桥年份不同",
             "claim_ids": [old, new]},
            {"conflict_key": "unrelated", "description": "另一件事情仍待确认",
             "claim_ids": [old, new]},
        ],
        "corrections": [{"old_timeline_index": 0, "new_timeline_index": 1,
                         "evidence_quote": "更正：不是1970年，是1971年。",
                         "conflict_keys": ["bridge_year"]}],
    }


def sources():
    return {"claims": [
        {"claim_id": "old", "claim_text": "1962年出生，1970年和母亲过桥。",
         "source_quote": "1962年出生，1970年和母亲过桥。", "chapter_id": "chapter"},
        {"claim_id": "new", "claim_text": "更正：不是1970年，是1971年。",
         "source_quote": "更正：不是1970年，是1971年。", "chapter_id": "chapter"},
    ]}


def test_correction_removes_only_replaced_event_and_resolves_only_named_conflict():
    result = validate("graph", graph(), json.dumps(sources()))
    assert {anchor["year"] for anchor in result["timeline"]} == {1962, 1971}
    assert result["conflicts"][0]["status"] == "resolved"
    assert "status" not in result["conflicts"][1]


@pytest.mark.parametrize("case", ["ambiguous", "cross_chapter", "reverse", "invented_quote",
                                 "bad_index", "wrong_conflict", "missing_date"])
def test_corrections_fail_closed(case):
    output, source = graph(), sources()
    if case == "ambiguous":
        quote = "更正：可能不是1970年，是1971年。"
        source["claims"][1]["source_quote"] = quote
        output["corrections"][0]["evidence_quote"] = quote
    elif case == "cross_chapter":
        source["claims"][1]["chapter_id"] = "another"
    elif case == "reverse":
        source["claims"].reverse()
    elif case == "invented_quote":
        source["claims"][1]["source_quote"] = "1971年过桥"
    elif case == "bad_index":
        output["corrections"][0]["old_timeline_index"] = 99
    elif case == "wrong_conflict":
        output["corrections"][0]["conflict_keys"] = ["invented"]
    else:
        output["timeline"][0]["year"] = 1969
    with pytest.raises(ValueError):
        validate("graph", output, json.dumps(source))


def test_voice_derived_claim_can_retain_correction_without_raw_transcript():
    source = sources()
    source["claims"][1]["source_quote"] = ""
    assert len(validate("graph", graph(), json.dumps(source))["timeline"]) == 2


def test_existing_conflict_is_resolved_and_source_claims_are_preserved(client, monkeypatch):
    person = client.post("/v1/persons", json={"display_name": "纠错测试"}).json()
    chapter = client.get("/v1/chapters").json()[0]
    tenant = get_settings().default_tenant_id
    with SessionLocal() as db:
        claims = []
        for source in sources()["claims"]:
            claim = MemoryClaim(tenant_id=tenant, subject_id=UUID(person["id"]),
                                chapter_id=UUID(chapter["id"]), claim_text=source["claim_text"],
                                source_quote=source["source_quote"])
            db.add(claim)
            db.flush()
            claims.append(claim)
        old_id, new_id = map(lambda c: str(c.id), claims)
        conflict = MemoryConflict(tenant_id=tenant, subject_id=UUID(person["id"]),
                                  claim_ids=[old_id, new_id], conflict_key="bridge_year",
                                  description="旧年份冲突", status="open")
        db.add(conflict)
        db.commit()
        conflict_id = conflict.id
        monkeypatch.setattr(get_settings(), "llm_provider", "openai-compatible")
        monkeypatch.setattr(get_settings(), "openai_compatible_base_url", "https://test/v1")
        monkeypatch.setattr(get_settings(), "openai_compatible_api_key", "test")
        monkeypatch.setattr(get_settings(), "memory_llm_model", "test")
        monkeypatch.setattr(OpenAICompatibleClient, "chat_json",
                            lambda *_: copy.deepcopy(graph(old_id, new_id)))
        service._compile_entities_and_timeline_ai(db, tenant, claims)
        db.commit()
        assert db.get(MemoryConflict, conflict_id).status == "resolved"
        assert len(list(db.scalars(select(MemoryConflict)))) == 2
        assert {a.year for a in db.scalars(select(TimelineAnchor))} == {1962, 1971}
        assert len(list(db.scalars(select(MemoryClaim)))) == 2
        service._compile_entities_and_timeline_ai(db, tenant, claims)
        db.commit()
        assert len(list(db.scalars(select(MemoryConflict)))) == 2

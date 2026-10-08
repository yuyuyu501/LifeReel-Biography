import copy
import json
from uuid import UUID

import pytest
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.interview.models import InterviewRound
from lifereel_api.modules.memory.facts import fact_evidence
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.modules.memory.structured import validate
from lifereel_api.modules.orchestration.service import execute_turn
from lifereel_api.modules.orchestration.skills import ScriptSkill
from lifereel_api.modules.script import service as scripts
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


def fact_graph(
    old="old", new="new", value="福州", quote="剧本里的出生地写错了，正确是福州，请修改。"
):
    return {
        "entities": [],
        "timeline": [],
        "conflicts": [],
        "fact_corrections": [
            {
                "target_claim_id": old,
                "correction_claim_id": new,
                "old_text": "泉州",
                "new_text": value,
                "evidence_quote": quote,
                "conflict_keys": [],
            }
        ],
    }


def sources(quote="剧本里的出生地写错了，正确是福州，请修改。"):
    return {
        "claims": [
            {
                "claim_id": "old",
                "chapter_id": "chapter",
                "claim_text": "1952年出生于泉州，退休住杭州。",
                "source_quote": "1952年出生于泉州，退休住杭州。",
            },
            {
                "claim_id": "new",
                "chapter_id": "chapter",
                "claim_text": quote,
                "source_quote": quote,
            },
        ]
    }


def test_correction_supports_places_without_repeating_old_value():
    result = validate("graph", fact_graph(), json.dumps(sources()))
    assert result["fact_corrections"][0]["new_text"] == "福州"


@pytest.mark.parametrize(
    "case",
    [
        "uncertain",
        "ordinary_fact",
        "other_chapter",
        "unknown_source",
        "invented_quote",
        "invented_value",
        "ambiguous_target",
        "reverse",
    ],
)
def test_fact_patch_rejects_ungrounded_or_unrelated_replacements(case):
    output, context = fact_graph(), sources()
    patch = output["fact_corrections"][0]
    if case == "uncertain":
        patch["evidence_quote"] = "更正：可能是福州。"
        context["claims"][1]["source_quote"] = patch["evidence_quote"]
    elif case == "ordinary_fact":
        patch["evidence_quote"] = "我后来到福州旅游。"
        context["claims"][1]["source_quote"] = patch["evidence_quote"]
    elif case == "other_chapter":
        context["claims"][1]["chapter_id"] = "other"
    elif case == "unknown_source":
        patch["target_claim_id"] = "other-tenant"
    elif case == "invented_quote":
        context["claims"][1]["source_quote"] = "今天休息"
    elif case == "invented_value":
        patch["new_text"] = "北京"
    elif case == "ambiguous_target":
        context["claims"][0]["claim_text"] += "朋友住在泉州。"
    else:
        context["claims"].reverse()
    with pytest.raises(ValueError):
        validate("graph", output, json.dumps(context))


def test_only_specified_previous_conflict_is_closed():
    context = sources()
    context["previous_conflicts"] = [
        {
            "conflict_key": "birthplace",
            "description": "出生地不一致",
            "claim_ids": ["old", "new"],
            "status": "open",
        },
        {
            "conflict_key": "other",
            "description": "另一个未解决问题",
            "claim_ids": ["old", "new"],
            "status": "open",
        },
    ]
    output = fact_graph()
    output["fact_corrections"][0]["conflict_keys"] = ["birthplace"]
    result = validate("graph", output, json.dumps(context))
    assert result["conflicts"] == [
        {
            "conflict_key": "birthplace",
            "description": "出生地不一致",
            "claim_ids": ["old", "new"],
            "status": "resolved",
        }
    ]


@pytest.mark.parametrize(
    "year,quote,expected",
    [
        (0, "后来开始练习书法", None),
        (20, "20岁开始工作", None),
        (195, "上世纪五十年代出生", None),
        (1750, "家谱明确记载祖辈1750年迁居", 1750),
        (1952, "1952年出生", 1952),
    ],
)
def test_non_calendar_year_does_not_abort_valid_memory(year, quote, expected):
    data = {"claims": [{"claim_id": "a", "source_quote": quote, "claim_text": quote}]}
    result = validate(
        "graph",
        {
            "entities": [],
            "conflicts": [],
            "timeline": [
                {
                    "year": year,
                    "time_text": quote,
                    "event_text": quote,
                    "precision": "year",
                    "source_claim_id": "a",
                },
            ],
        },
        json.dumps(data),
    )
    assert result["timeline"][0]["year"] == expected
    if expected is None:
        assert result["timeline"][0]["precision"] == "relative"


def test_later_dialogue_corrects_persisted_facts_and_script_without_editing_original(
    client, monkeypatch
):
    person = client.post("/v1/persons", json={"display_name": "对话纠错合成人物"}).json()
    chapter = client.get("/v1/chapters").json()[0]
    session = client.post(
        "/v1/interviews",
        json={"mode": "legacy", "subject_id": person["id"], "chapter_id": chapter["id"]},
    ).json()
    url = f"/v1/interviews/{session['id']}/turns"
    original = "1952年出生于泉州，退休后和老伴住在杭州，爱好书法，写字让我平静。"
    first = client.post(url, json={"answer_text": original, "idempotency_key": "dialogue-original"})
    assert first.status_code == 202 and first.json()["status"] == "completed", first.text
    original_round = first.json()["round_id"]
    settings = get_settings()
    for name, value in {
        "llm_provider": "openai-compatible",
        "openai_compatible_base_url": "https://synthetic.test/v1",
        "openai_compatible_api_key": "synthetic",
        "memory_llm_model": "synthetic",
        "interview_llm_model": "synthetic",
        "script_llm_model": "synthetic",
    }.items():
        monkeypatch.setattr(settings, name, value)
    correction = "剧本里的出生地写错了，正确是福州，请修改。"
    captured = []

    def model(self, system, user):
        data = json.loads(user)
        if "识别采访" in system:
            assert data["context"]["current_script"]
            return {
                "action": "interview",
                "has_new_facts": False,
                "instructions": "更正出生地",
                "is_correction": True,
            }
        if "口述史证据整理员" in system:
            return {"claim_text": correction, "claim_type": "place", "confidence": 1.0}
        if "知识图谱" in system:
            old, new = data["claims"]
            output = fact_graph(old["claim_id"], new["claim_id"])
            output["timeline"] = [
                {
                    "year": 195,
                    "time_text": "退休后",
                    "event_text": "在杭州生活",
                    "precision": "relative",
                    "source_claim_id": old["claim_id"],
                }
            ]
            return output
        if "人物小传" in system:
            assert data[0]["claim_text"].startswith("1952年出生于福州")
            assert data[0]["source_quote"] == ""
            return {"biography": "在福州出生，退休后住杭州，爱好书法。"}
        if "口述史采访者" in system:
            assert data["chapter_assessment"]["script_updated"] is True
            assert any("福州" in text for text in data["known_memories"])
            return {"next_question": "剧本已按福州更正。您最初是跟谁学写字的？", "intent": "event"}
        raise AssertionError("Unexpected model request: " + system[:35])

    def scenes(subject, payload, claims, profile, update_brief=None):
        evidence = [fact_evidence(c) for c in claims]
        captured.append(copy.deepcopy(evidence))
        assert "福州" in evidence[0]["claim_text"] and "泉州" not in evidence[0]["claim_text"]
        assert "杭州" in evidence[0]["claim_text"] and "书法" in evidence[0]["claim_text"]
        return None, scripts._rule_scenes(subject.display_name, claims, profile), "synthetic"

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", model)
    monkeypatch.setattr(scripts, "_llm_scenes", scenes)
    # A short correction to an existing script must not get stuck waiting for a new interview.
    monkeypatch.setattr(
        ScriptSkill,
        "assess",
        lambda *args: {
            "ready_for_script": False,
            "missing_topics": [],
            "reason": "short correction",
        },
    )
    body = {"answer_text": correction, "idempotency_key": "dialogue-correct-place"}
    second = client.post(url, json=body)
    assert second.status_code == 202, second.text
    with SessionLocal() as db:
        execute_turn(db, settings.default_tenant_id, UUID(second.json()["id"]))
    second = client.get(f"/v1/interviews/{session['id']}/workspace")
    result = second.json()["latest_workflow"]
    assert result["status"] == "completed", second.text
    assert result["script_brief"]["assessment"]["script_updated"]
    assert result["script_brief"]["turn_intent"]["has_new_facts"] is True
    assert captured
    with SessionLocal() as db:
        prior = db.get(InterviewRound, UUID(original_round))
        assert prior.answer_text == original and prior.answer_version == 1
        claim = db.scalar(select(MemoryClaim).where(MemoryClaim.source_round_id == prior.id))
        assert claim.claim_text == original and claim.source_quote == original
        assert claim.current_text == original.replace("泉州", "福州")
        assert len(claim.fact_overrides) == 1
    memory = client.get(f"/v1/memories?subject_id={person['id']}").json()
    assert any(row["claim_text"] == original.replace("泉州", "福州") for row in memory)
    workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    scene = workspace["script"]["scenes"][0]
    assert "福州" in scene["narration"] and "泉州" not in scene["narration"]
    assert client.post(url, json=body).json()["id"] == result["id"]
    assert len(captured) == 1

"""Regression coverage for incremental facts and optional strategy jobs."""

import json
from uuid import UUID, uuid4

import httpx
import pytest
from lifereel_api.modules.interview import advice, companion, historical_context, profile_service
from lifereel_api.modules.interview.models import InterviewSession, InterviewTurnWorkflow
from lifereel_api.modules.interview.profile_schemas import ProfilePatch
from lifereel_api.modules.jobs import dispatch
from lifereel_api.modules.jobs.models import Job
from lifereel_api.modules.orchestration.service import execute_turn
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient
from sqlalchemy import select
from test_interview_companion import candidate, review, run_profile, setup
from test_interview_companion import enhanced as enhanced

from lifereel_api.core.database import SessionLocal


def test_partial_event_update_preserves_details_and_evidence(client, enhanced, monkeypatch):
    profile, _ = setup(client)
    original = {
        "title": "修线圈",
        "time_raw": "1986年",
        "what": "第一次绕线圈烧坏了",
        "action": "重新拆开绕线",
        "people": ["师傅"],
    }
    with SessionLocal() as db:
        profile = profile_service.patch(
            db,
            enhanced.default_tenant_id,
            UUID(profile["id"]),
            ProfilePatch(
                expected_version=profile["version_number"],
                changes=[
                    {
                        "field_key": "work.events[]",
                        "record_key": "coil",
                        "value": original,
                    }
                ],
            ),
            actor="ai",
            source={
                "type": "test",
                "id": "original",
                "version": 1,
                "quotes": {"work.events[]:coil": "我烧坏了线圈，重新拆开绕线。"},
            },
        )

    def provider(self, system, data):
        material = json.loads(data)
        if system == companion.AUDIT_PROMPT:
            merged = material["candidate"]["changes"][0]["value"]
            assert all(merged[k] == v for k, v in original.items())
            return review(safe=[0])
        return candidate(
            material,
            "后来您怎样教徒弟？",
            [
                {
                    "field_key": "work.events[]",
                    "record_key": "coil",
                    "value": {"impact": "从此认真检查再通电"},
                    "quote": "从此我认真检查再通电。",
                }
            ],
        )

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", provider)
    result = run_profile(profile, "从此我认真检查再通电。")
    entry = next(e for e in result["profile"]["entries"] if e["record_key"] == "coil")
    assert entry["value"]["what"] == original["what"]
    assert entry["value"]["impact"] == "从此认真检查再通电"
    assert {e["id"] for e in entry["source"]["evidence"]} == {"original", "new-answer"}


@pytest.mark.parametrize("conflict", [False, True])
def test_time_expansion_is_not_string_conflict_but_audited_conflict_is_retained(
    client,
    enhanced,
    monkeypatch,
    conflict,
):
    profile, _ = setup(client)
    with SessionLocal() as db:
        profile = profile_service.patch(
            db,
            enhanced.default_tenant_id,
            UUID(profile["id"]),
            ProfilePatch(
                expected_version=profile["version_number"],
                changes=[
                    {
                        "field_key": "work.records[]",
                        "record_key": "factory",
                        "value": {"time_raw": "1986年", "place": "湖南", "title": "电机厂"},
                    }
                ],
            ),
            actor="ai",
            source={"type": "test", "id": "original"},
        )

    def provider(self, system, data):
        if system == companion.AUDIT_PROMPT:
            return review(safe=[0], conflicts=[0] if conflict else [])
        return candidate(
            json.loads(data),
            "厂里做什么工作？",
            [
                {
                    "field_key": "work.records[]",
                    "record_key": "factory",
                    "value": {
                        "time_raw": "1987年" if conflict else "1986至1997年",
                        "place": "湖南湘潭",
                    },
                    "quote": "我在厂里的时间是1987年。"
                    if conflict
                    else "我1986至1997年在湖南湘潭。",
                }
            ],
        )

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", provider)
    result = run_profile(
        profile, "我在厂里的时间是1987年。" if conflict else "我1986至1997年在湖南湘潭。"
    )
    entry = next(e for e in result["profile"]["entries"] if e["record_key"] == "factory")
    assert (entry["certainty"] == "disputed") == conflict
    if not conflict:
        assert entry["value"]["title"] == "电机厂"


@pytest.mark.parametrize(
    "history_request",
    [
        {"event": "flood", "region": "湘潭", "year_start": 1998, "year_end": 1998},
        {"event": "flood", "region": "湖南", "year_start": 1998, "year_end": 1998},
    ],
)
def test_optional_history_errors_do_not_discard_personal_facts(
    client,
    enhanced,
    monkeypatch,
    history_request,
):
    profile, _ = setup(client)
    answer = "1998年湖南发洪水，我搬了两袋米。"

    def lookup(*args):
        raise httpx.ReadTimeout("synthetic history timeout")

    def provider(self, system, data):
        if system == companion.AUDIT_PROMPT:
            return review(safe=[0])
        return candidate(
            json.loads(data),
            "您和谁一起搬米？",
            [
                {
                    "field_key": "turning.events[]",
                    "record_key": "new",
                    "value": {"what": "1998年搬两袋米", "action": "搬米"},
                    "quote": answer,
                }
            ],
            history_request=history_request,
        )

    monkeypatch.setattr(historical_context, "lookup", lookup)
    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", provider)
    result = run_profile(profile, answer)
    assert result["audit"]["verdict"] == "pass"
    assert result["audit"]["history"]["status"] in {"failed", "invalid_request"}
    assert any(e["field_key"] == "turning.events[]" for e in result["profile"]["entries"])


@pytest.mark.parametrize(
    "answer,field,value",
    [
        ("我在湘潭农村长大。", "identity.birth_place", "湘潭农村"),
        (
            "父亲2008年搬到长沙我哥家。我仍在湘潭开店。",
            "turning.moves[]",
            {"what": "2008年搬到长沙哥哥家"},
        ),
    ],
)
def test_new_person_attribution_guards_survive_a_mistaken_auditor(
    client,
    enhanced,
    monkeypatch,
    answer,
    field,
    value,
):
    profile, _ = setup(client)

    def provider(self, system, data):
        if system == companion.AUDIT_PROMPT:
            return review(safe=list(range(len(json.loads(data)["candidate"]["changes"]))))
        return candidate(
            json.loads(data),
            "您后来做什么工作？",
            [
                {
                    "field_key": field,
                    "record_key": "new" if field.endswith("[]") else "single",
                    "value": value,
                    "quote": answer,
                }
            ],
        )

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", provider)
    result = run_profile(profile, answer)
    assert not any(e["field_key"] == field for e in result["profile"]["entries"])
    assert result["audit"]["dropped_program_changes"] == 1


def queued_advice(client, settings, monkeypatch):
    profile, session = setup(client)
    with SessionLocal() as db:
        row = db.get(InterviewSession, UUID(session["id"]))
        row.interview_state = {"topic": "修理", "topic_turns": 3, "turn_count": 3}
        db.commit()

    def provider(self, system, data):
        material = json.loads(data)
        assert self.model == settings.interview_llm_model
        if system == companion.AUDIT_PROMPT:
            return review(safe=[0])
        return candidate(
            material,
            "后来教过谁修理？",
            [
                {
                    "field_key": "work.meaning",
                    "value": "做事认真",
                    "quote": "从此我做事认真。",
                }
            ],
            topic="修理",
        )

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", provider)
    submitted = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "answer_text": "从此我做事认真。",
            "idempotency_key": str(uuid4()),
        },
    )
    assert submitted.status_code == 202
    with SessionLocal() as db:
        workflow = execute_turn(db, settings.default_tenant_id, UUID(submitted.json()["id"]))
        assert workflow.status == "completed"
        job = db.scalar(select(Job).where(Job.kind == advice.KIND))
        assert job and job.status == "queued"
        return profile, session, job.id, workflow.id


@pytest.mark.parametrize("outcome", ["ready", "timeout", "stale_after", "invalid_source"])
def test_advisor_is_optional_fenced_and_never_changes_profile(
    client,
    enhanced,
    monkeypatch,
    outcome,
):
    profile, session, job_id, workflow_id = queued_advice(client, enhanced, monkeypatch)
    before = client.get(f"/v1/life-profiles/{profile['id']}").json()

    def sol(self, system, data):
        assert self.model == enhanced.interview_review_llm_model
        material = json.loads(data)
        if outcome == "timeout":
            raise httpx.ReadTimeout("synthetic advisor timeout")
        if outcome == "stale_after":
            with SessionLocal() as other:
                row = other.get(InterviewSession, UUID(session["id"]))
                row.interview_state = {**row.interview_state, "topic": "另一主题"}
                other.commit()
        return {
            "action": "transition",
            "topic": "带徒弟",
            "goal": "从技能到人物的关系",
            "directions": ["询问是否教过他人修理"],
            "cautions": ["不能假定已有徒弟"],
            "used_source_ids": [
                "invented" if outcome == "invalid_source" else material["source_ids"][0]
            ],
        }

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", sol)
    with SessionLocal() as db:
        claim = dispatch.claim_job(db, "interview")
        assert claim["job_id"] == str(job_id)
        dispatch.execute_claim(db, job_id, UUID(claim["token"]))
        job = db.get(Job, job_id)
        if outcome in {"timeout", "invalid_source"}:
            assert job.status == "failed"
        else:
            assert job.result["status"] == ("stale" if outcome == "stale_after" else "ready")
        suggestion = advice.ready(
            db,
            enhanced.default_tenant_id,
            db.get(InterviewSession, UUID(session["id"])),
            "我想继续聊。",
        )
        assert bool(suggestion) == (outcome == "ready")
        assert db.get(InterviewTurnWorkflow, workflow_id).status == "completed"
        monkeypatch.setattr(
            OpenAICompatibleClient, "chat_json", lambda *a: pytest.fail("duplicate optional call")
        )
        advice.execute(db, enhanced.default_tenant_id, job_id)
    assert client.get(f"/v1/life-profiles/{profile['id']}").json() == before


def test_advisor_stale_before_call_and_no_replay_after_interruption(client, enhanced, monkeypatch):
    _, session, job_id, _ = queued_advice(client, enhanced, monkeypatch)
    monkeypatch.setattr(
        OpenAICompatibleClient,
        "chat_json",
        lambda *a: pytest.fail("stale or interrupted advice must not call Sol"),
    )
    with SessionLocal() as db:
        row = db.get(InterviewSession, UUID(session["id"]))
        row.interview_state = {**row.interview_state, "action": "pause"}
        db.commit()
        assert advice.execute(db, enhanced.default_tenant_id, job_id).result["status"] == "stale"
        job = db.get(Job, job_id)
        job.status = "running"
        db.commit()
        assert (
            advice.execute(db, enhanced.default_tenant_id, job_id).error_code
            == "ADVICE_INTERRUPTED"
        )


def test_foreground_priority_single_advisor_and_reserved_capacity(client, enhanced):
    with SessionLocal() as db:
        for kind in [advice.KIND, advice.KIND, "interview.turn.process"]:
            db.add(Job(tenant_id=enhanced.default_tenant_id, kind=kind, payload={}))
        db.commit()
        first = dispatch.claim_job(db, "interview")
        assert db.get(Job, UUID(first["job_id"])).kind == "interview.turn.process"
        second = dispatch.claim_job(db, "interview")
        assert db.get(Job, UUID(second["job_id"])).kind == advice.KIND
        assert dispatch.claim_job(db, "interview") is None


@pytest.mark.parametrize("mutation", ["profile", "source", "submission"])
def test_advisor_rejects_each_stale_anchor_before_call(client, enhanced, monkeypatch, mutation):
    from lifereel_api.modules.interview.models import InterviewRound
    from lifereel_api.modules.interview.profile_models import LifeProfile

    profile, session, job_id, _ = queued_advice(client, enhanced, monkeypatch)
    if mutation == "submission":
        response = client.post(
            f"/v1/interviews/{session['id']}/turns",
            json={
                "answer_text": "后来我换了工作。",
                "idempotency_key": str(uuid4()),
            },
        )
        assert response.status_code == 202
    with SessionLocal() as db:
        if mutation == "profile":
            db.get(LifeProfile, UUID(profile["id"])).version_number += 1
        if mutation == "source":
            source = db.get(Job, job_id).payload["source"]["id"]
            db.get(InterviewRound, UUID(source)).answer_version += 1
        db.commit()
        monkeypatch.setattr(
            OpenAICompatibleClient,
            "chat_json",
            lambda *a: pytest.fail("stale advice must not call Sol"),
        )
        assert advice.execute(db, enhanced.default_tenant_id, job_id).result["status"] == "stale"


def test_advisor_dedup_cooldown_and_invalid_commands(client, enhanced, monkeypatch):
    _, session, job_id, workflow_id = queued_advice(client, enhanced, monkeypatch)
    with SessionLocal() as db:
        workflow = db.get(InterviewTurnWorkflow, workflow_id)
        row = db.get(InterviewSession, UUID(session["id"]))
        assert advice.schedule(db, enhanced.default_tenant_id, workflow, row) is None
        job = db.get(Job, job_id)
        job.status = "failed"
        db.commit()
        assert advice.schedule(db, enhanced.default_tenant_id, workflow, row) is None
        with pytest.raises(Exception) as error:
            advice.Advice.model_validate(
                {
                    "action": "transition",
                    "topic": "工作",
                    "goal": "追问",
                    "directions": ["追问"],
                    "used_source_ids": ["current:1"],
                    "changes": [
                        {
                            "field_key": "identity.birth_place",
                            "value": "捏造的出生地",
                        }
                    ],
                }
            )
        assert "extra_forbidden" in str(error.value)


def test_member_array_update_merges_the_same_person_without_duplicates():
    from lifereel_api.modules.interview.profile_updates import merge

    old = [
        {"person": "父亲", "birth_year": "1938", "skill": "竹编"},
        {"person": "母亲", "skill": "种菜"},
    ]
    merged = merge(old, [{"person": "父亲", "status": "在世"}])
    assert len(merged) == 2
    assert merged[0] == {**old[0], "status": "在世"}
    assert merged[1] == old[1]
    corrected = merge(old, [{"person": "父亲", "birth_year": "1939"}], corrected=True)
    assert corrected[0]["birth_year"] == "1939" and corrected[1] == old[1]


def test_growth_label_and_book_name_are_not_inferred_birth_or_legal_identity(
    client,
    enhanced,
    monkeypatch,
):
    profile, _ = setup(client)
    answer = "我是周建国，书里叫我建国。我在黄冈农村长大。"

    def provider(self, system, data):
        material = json.loads(data)
        if system == companion.AUDIT_PROMPT:
            return review(
                safe=[1],
                conflicts=[0],
                links={"0": material["evidence"]["current_entries"][0]["id"]},
            )
        return candidate(
            material,
            "小时候主要和谁住在一起？",
            [
                {"field_key": "identity.preferred_name", "value": "建国", "quote": "书里叫我建国"},
                {
                    "field_key": "identity.birth_place",
                    "value": {"growth_place": "黄冈农村"},
                    "quote": "我在黄冈农村长大。",
                },
            ],
        )

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", provider)
    result = run_profile(profile, answer)
    assert result["audit"]["verdict"] == "pass"
    entries = {e["field_key"]: e for e in result["profile"]["entries"]}
    assert entries["identity.preferred_name"]["value"] == "建国"
    assert entries["identity.birth_place"]["value"] == {"growth_place": "黄冈农村"}
    assert entries["identity.birth_place"]["certainty"] == "reported"


def test_attendance_cannot_be_promoted_to_graduation_even_if_auditor_passes(
    client,
    enhanced,
    monkeypatch,
):
    profile, _ = setup(client)
    answer = "我1986到1989年在乡中学，中学以后不再上学。我喜欢画图。"

    def provider(self, system, data):
        material = json.loads(data)
        if system == companion.AUDIT_PROMPT:
            return review(safe=list(range(len(material["candidate"]["changes"]))))
        return candidate(
            material,
            "以后学了什么手艺？",
            [
                {
                    "field_key": "learning.choices[]",
                    "record_key": "new",
                    "value": {"title": "中学毕业后不再上学"},
                    "quote": answer,
                },
                {"field_key": "learning.interests", "value": "画图", "quote": "我喜欢画图。"},
            ],
        )

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", provider)
    result = run_profile(profile, answer)
    assert result["audit"]["dropped_program_changes"] == 1
    assert not any(e["field_key"] == "learning.choices[]" for e in result["profile"]["entries"])
    assert any(e["value"] == "画图" for e in result["profile"]["entries"])


def test_storage_metadata_and_missing_narrative_values_are_normalized_before_review(
    client,
    enhanced,
    monkeypatch,
):
    profile, _ = setup(client)
    answer = "书里叫我建国。答应别人的事情要尽力做到。"

    def provider(self, system, data):
        material = json.loads(data)
        if system == companion.AUDIT_PROMPT:
            assert material["candidate"]["changes"][0]["value"] == "建国"
            assert material["candidate"]["changes"][1]["value"] == "答应别人的事情要尽力做到。"
            return review(safe=[0, 1])
        return candidate(
            material,
            "小时候和谁一起生活？",
            [
                {"field_key": "identity.preferred_name", "quote": "书里叫我建国"},
                {
                    "field_key": "legacy.messages",
                    "quote": "答应别人的事情要尽力做到。",
                    "source": {"id": "fabricated", "quote": "made up"},
                    "source_id": "fabricated",
                    "version_number": 100,
                },
            ],
        )

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", provider)
    result = run_profile(profile, answer)
    assert result["audit"]["verdict"] == "pass" and result["audit"]["candidate_normalizations"] == 2
    entry = next(e for e in result["profile"]["entries"] if e["field_key"] == "legacy.messages")
    assert entry["source"]["id"] == "new-answer"
    assert "fabricated" not in json.dumps(entry)


def test_duplicate_pending_topics_are_combined_before_audit(client, enhanced, monkeypatch):
    profile, _ = setup(client)
    answer = "结婚照下次再找。摆摊故事下次再讲。"

    def provider(self, system, data):
        material = json.loads(data)
        if system == companion.AUDIT_PROMPT:
            assert len(material["candidate"]["changes"]) == 1
            assert material["candidate"]["changes"][0]["quote"] == answer
            assert material["candidate"]["changes"][0]["value"] == [
                {"topic": "结婚照"},
                {"topic": "摆摊故事"},
            ]
            return review(safe=[0])
        return candidate(
            material,
            "您想先讲哪段其他的经历？",
            [
                {
                    "field_key": "legacy.open_threads",
                    "record_key": "new",
                    "value": {"topic": "结婚照"},
                    "quote": "结婚照下次再找。",
                },
                {
                    "field_key": "legacy.open_threads",
                    "record_key": "new",
                    "value": {"topic": "摆摊故事"},
                    "quote": "摆摊故事下次再讲。",
                },
            ],
            action="transition",
        )

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", provider)
    result = run_profile(profile, answer)
    entries = [e for e in result["profile"]["entries"] if e["field_key"] == "legacy.open_threads"]
    assert len(entries) == 1 and len(entries[0]["value"]) == 2


def test_graduation_after_variant_is_rejected(enhanced):
    material = {
        "new_answer": "1986至1989年在乡中学。",
        "source_ids": ["current:1"],
        "current_entries": [],
        "recent_questions": [],
        "recent_dialogue": [],
    }
    output = candidate(material, "您从乡中学毕业之后做了什么？")
    assert "unsupported_graduation_presupposition" in companion.program_issues(output, material)[1]


def test_cross_sentence_relative_move_is_rejected_even_if_auditor_passes(
    client, enhanced, monkeypatch,
):
    profile, _ = setup(client)
    answer = "去的是长沙，在我弟弟家住，不是去世了。父亲现在还活着，不是我搬家。"

    def provider(self, system, data):
        material = json.loads(data)
        if system == companion.AUDIT_PROMPT:
            return review(safe=list(range(len(material["candidate"]["changes"]))))
        return candidate(material, "父亲搬家后和您联系多吗？", [
            {"field_key": "turning.moves[]", "record_key": "new",
             "value": {"what": "去长沙弟弟家住"}, "quote": "去的是长沙，在我弟弟家住"},
            {"field_key": "family.members[]", "record_key": "new",
             "value": {"person": "父亲", "what": "去长沙弟弟家住，仍健在"}, "quote": answer},
        ])

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", provider)
    result = run_profile(profile, answer)
    assert result["audit"]["dropped_program_changes"] == 1
    assert not any(e["field_key"] == "turning.moves[]" for e in result["profile"]["entries"])
    assert any(e["field_key"] == "family.members[]" for e in result["profile"]["entries"])


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_conflict_cannot_link_another_field(client, enhanced, monkeypatch, repair_succeeds):
    profile, _ = setup(client)
    seed = next(e for e in profile["entries"] if e["field_key"] == "identity.preferred_name")
    audits = 0

    def provider(self, system, data):
        nonlocal audits
        material = json.loads(data)
        if system == companion.AUDIT_PROMPT:
            audits += 1
            assert material["valid_conflict_targets"]["0"] == []
            assert material["current_answer_evidence"]["text"] == "1992年我搬到县城。"
            if repair_succeeds and audits == 2:
                return review(safe=[0])
            return review(safe=[0], conflicts=[0], links={"0": seed["id"]})
        return candidate(material, "刚搬家时如何适应？", [
            {"field_key": "turning.moves[]", "record_key": "new",
             "value": {"what": "搬到县城", "time_raw": "1992年"}, "quote": "1992年我搬到县城。"},
        ])

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", provider)
    result = run_profile(profile, "1992年我搬到县城。")
    assert audits == 2
    entries = result["profile"]["entries"]
    assert next(e for e in entries if e["id"] == seed["id"])["value"] == seed["value"]
    assert any(e["field_key"] == "turning.moves[]" for e in entries) == repair_succeeds
    if not repair_succeeds:
        assert result["audit"]["rejection_reason"] == "invalid_conflict_source"


def test_memory_gap_streak_survives_topic_changes_and_replay():
    state = {"turn_count": 4, "memory_gap_turns": 1, "topic": "父亲"}
    source = {"id": "answer-5", "version": 1}
    decision = {"action": "transition", "topic": "母亲"}
    advanced = companion.next_state(state, decision, source, answer_text="这些细节也记不清了。")
    assert advanced["memory_gap_turns"] == 2
    assert advice.policy(advanced, "小时候日常想不起来。等以后再讲。 ")["change_stage"]
    assert companion.next_state(advanced, decision, source, answer_text="记不清") == advanced
    resumed = companion.next_state(
        advanced, decision, {"id": "answer-6", "version": 1}, answer_text="1990年开始学修柴油机。",
    )
    assert resumed["memory_gap_turns"] == 0


def test_auditor_preserves_values_and_quotes_without_storage_metadata(enhanced, monkeypatch):
    material = {
        "new_answer": "我现在喜欢种花。", "source_ids": ["current:1"],
        "current_entries": [{
            "id": "entry-1", "field_key": "present.interests", "record_key": "single",
            "value": "听戏", "state": "filled", "certainty": "reported",
            "version_number": 100, "source_id": "entry:entry-1:v100",
            "source": {"id": "answer-0", "quote": "我喜欢听戏。", "evidence": [
                {"id": "answer-0", "version": 1, "quote": "我喜欢听戏。"},
            ]},
        }],
        "recent_dialogue": [], "recent_questions": [], "state": {},
    }
    output = candidate(material, "您喜欢种什么花？", [
        {"field_key": "present.interests", "record_key": "single",
         "value": "种花", "quote": "我现在喜欢种花。"},
    ])

    def provider(self, system, data):
        packet = json.loads(data)
        old = packet["evidence"]["current_entries"][0]
        assert old["value"] == "听戏" and old["source"]["quote"] == "我喜欢听戏。"
        assert old["source"]["evidence_quotes"] == ["我喜欢听戏。"]
        assert "version_number" not in old and "source_id" not in old
        assert packet["valid_conflict_targets"]["0"] == ["entry-1"]
        return review(safe=[0])

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", provider)
    assert companion._audit(output, material).safe_change_indices == [0]

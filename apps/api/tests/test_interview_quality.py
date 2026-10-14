"""Coverage repair must preserve evidence, boundaries and already approved facts."""

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from lifereel_api.modules.interview import companion, quality
from lifereel_api.modules.interview.profile_extraction import process
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal

ANSWER = "我早上散步。儿子住长沙，女儿住湘潭，每周末和我联系。"
RELATIONS = "儿子住长沙，女儿住湘潭，每周末和我联系。"


@pytest.fixture
def enabled(monkeypatch):
    settings = get_settings()
    for key, value in {
        "llm_provider": "openai-compatible", "interview_enhancements_enabled": True,
        "interview_quality_enabled": True, "interview_sync_assistance_enabled": True,
        "interview_review_enabled": True, "interview_turn_budget_seconds": 240,
        "interview_llm_model": "synthetic-lite", "interview_review_llm_model": "synthetic-sol",
        "openai_compatible_base_url": "http://synthetic.invalid/v1",
        "openai_compatible_api_key": "synthetic",
    }.items():
        monkeypatch.setattr(settings, key, value)
    return settings


def candidate(data, field="present.daily_life", value="早上散步", quote="我早上散步。"):
    return {"changes": [{"field_key": field, "value": value, "quote": quote}],
            "next_question": "散步时，您通常会去哪里？",
            "decision": {"action": "deepen_scene", "used_source_ids": [data["source_ids"][0]],
                         "question_goal": "了解散步地点"}}


def inspection(data):
    changes = data["accepted_changes"]
    result = {"facts": [], "question_claims": [], "question_issues": []}
    for claim, field, quote in [
        ("早晨散步", "present.daily_life", "我早上散步。"),
        ("儿子住长沙", "present.relationships", RELATIONS),
        ("女儿住湘潭", "present.relationships", RELATIONS),
        ("子女每周末联系本人", "present.relationships", RELATIONS),
    ]:
        matches = [{"field": field, "change_index": i, "entry_id": None}
                   for i, c in enumerate(changes) if c["field_key"] == field]
        result["facts"].append({"claim": claim, "quote": quote, "fields": [field],
                                "matches": matches[:1]})
    return result


def run(client, answer=ANSWER):
    person = client.post("/v1/persons", json={"display_name": "覆盖检查合成人物"}).json()
    session = client.post("/v1/interviews", json={"subject_id": person["id"]}).json()
    with SessionLocal() as db:
        result = process(db, get_settings().default_tenant_id, UUID(session["profile_id"]),
                         answer, {"type": "interview_round", "id": "synthetic", "version": 1},
                         uuid4())
    return result, session


def provider(self, system, text):
    data = json.loads(text)
    if system == quality.INVENTORY_PROMPT:
        return {"facts": inspection({"accepted_changes": []})["facts"]}
    if system == companion.AUDIT_PROMPT:
        return {"verdict": "pass",
                "safe_change_indices": list(range(len(data["candidate"]["changes"]))),
                "issues": []}
    if system == quality.INSPECT_PROMPT:
        return inspection(data)
    if system == quality.REPAIR_PROMPT:
        assert self.model in {"synthetic-sol", "synthetic-lite"}
        assert len(data["missing_facts"]) == 3
        return {"changes": [{"field_key": "present.relationships", "value": RELATIONS,
                              "quote": RELATIONS}], "next_question": None, "decision": None}
    return candidate(data)


def test_omission_repaired_without_erasing_approved_fact(client, enabled, monkeypatch):
    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", provider)
    result, session = run(client)
    values = {e["field_key"]: e["value"] for e in result["profile"]["entries"]}
    assert values["present.daily_life"] == "早上散步"
    assert values["present.relationships"] == RELATIONS
    assert result["audit"]["quality"]["sync_assistance_calls"] == 2
    assert result["audit"]["quality"]["pending_facts"] == 0
    assert all(t["status"] == "saved" and t["entry_id"]
               for f in result["audit"]["fact_ledger"] for t in f["targets"])
    history = client.get(f"/v1/life-profiles/{session['profile_id']}/history").json()
    assert any(c.get("metadata", {}).get("interview_audit", {}).get("fact_ledger")
               for revision in history for c in revision["changes"])


def test_uncertain_paid_repair_not_retried_and_pending_facts_persist(client, enabled, monkeypatch):
    calls = []

    def timed_out(self, system, text):
        if system == quality.REPAIR_PROMPT:
            calls.append(self.model)
            raise httpx.ReadTimeout("synthetic")
        return provider(self, system, text)

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", timed_out)
    result, _ = run(client)
    assert calls == ["synthetic-sol"]
    assert result["audit"]["quality"]["pending_facts"] == 3
    assert result["next_question"].startswith("有些资料的归类还待核对。")
    assert any(e["field_key"] == "present.daily_life" for e in result["profile"]["entries"])
    assert not any(e["field_key"] == "present.relationships" for e in result["profile"]["entries"])


def test_repair_cannot_hide_missing_fact_by_changing_inventory(client, enabled, monkeypatch):
    count = 0

    def changed(self, system, text):
        nonlocal count
        result = provider(self, system, text)
        if system == quality.INSPECT_PROMPT:
            count += 1
            if count == 2:
                result["facts"] = result["facts"][:1]
        return result

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", changed)
    result, _ = run(client)
    assert len(result["audit"]["fact_ledger"]) == 4
    assert result["audit"]["quality"]["status"] == "partial"
    assert result["audit"]["quality"]["pending_facts"] == 3


def test_question_presupposition_checked_and_rewritten(client, enabled, monkeypatch):
    def questioning(self, system, text):
        data = json.loads(text)
        if system == quality.INSPECT_PROMPT:
            result = inspection(data)
            if "担心" in data["next_question"]:
                result["question_claims"] = [{"claim": "本人担心孩子", "status": "unsupported"}]
            return result
        if system == quality.REPAIR_PROMPT:
            result = provider(self, system, text)
            result["next_question"] = "您和孩子联系时，通常会聊些什么？"
            result["decision"] = {"action": "deepen_scene",
                                  "used_source_ids": [data["source_ids"][0]],
                                  "question_goal": "了解联系内容"}
            return result
        result = provider(self, system, text)
        if system not in {companion.AUDIT_PROMPT, quality.INVENTORY_PROMPT}:
            result["next_question"] = "您担心孩子在外地生活，通常怎么安慰他们？"
        return result

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", questioning)
    result, _ = run(client)
    assert result["next_question"] == "您和孩子联系时，通常会聊些什么？"
    assert result["audit"]["quality"]["question_issues"] == []


@pytest.mark.parametrize("mutation", ["wrong_field", "wrong_index", "missing_quote", "fake_source"])
def test_inventory_and_question_evidence_are_validated(enabled, mutation):
    data = {"new_answer": ANSWER, "source_ids": ["current:synthetic:v1"],
            "recent_dialogue": [], "current_entries": [], "state": {}}
    output = candidate(data)
    output["changes"][0].update(state="filled", certainty="reported", record_key="single")
    raw = inspection({"accepted_changes": output["changes"]})
    if mutation == "wrong_field":
        raw["facts"][0]["matches"][0]["field"] = "present.relationships"
    elif mutation == "wrong_index":
        raw["facts"][0]["matches"][0]["change_index"] = 3
    elif mutation == "missing_quote":
        raw["facts"][0]["quote"] = "用户没有说过"
    else:
        raw["question_claims"] = [{"claim": "养老", "status": "supported",
                                    "source_id": "news:synthetic", "support_quote": "养老"}]

    class Stub:
        def chat_json(self, *args):
            return raw

    if mutation == "fake_source":
        assert quality.inspect(Stub(), output, data).question_claims[0].status == "unsupported"
    elif mutation == "missing_quote":
        with pytest.raises(ValueError):
            quality.inspect(Stub(), output, data)
    else:
        checked = quality.inspect(Stub(), output, data)
        assert checked.facts[0].matches == []
        assert checked.match_issues
        assert quality.ledger(checked, "current:synthetic:v1")[0]["status"] == "pending"


def test_recheck_uses_frozen_ids_and_preserves_all_facts(enabled):
    data = {"new_answer": ANSWER, "source_ids": ["current:synthetic:v1"],
            "recent_dialogue": [], "current_entries": [], "state": {}}
    output = candidate(data)
    output["changes"][0].update(state="filled", certainty="reported", record_key="single")
    raw = inspection({"accepted_changes": output["changes"]})

    class Stub:
        def chat_json(self, *args):
            return raw

    first = quality.inspect(Stub(), output, data)
    frozen = [f.model_dump(exclude={"matches"}) for f in first.facts]
    for i, fact in enumerate(raw["facts"]):
        fact.update(fact_id=i, claim="复查不能改掉原来的内容", fields=[])
    raw["facts"].reverse()
    final = quality.inspect(Stub(), output, data, frozen_facts=frozen)
    assert [f.model_dump(exclude={"matches"}) for f in final.facts] == frozen
    raw["facts"].pop()
    with pytest.raises(ValueError, match="fact_inventory_changed"):
        quality.inspect(Stub(), output, data, frozen_facts=frozen)


def test_generated_entry_value_cannot_be_question_evidence(enabled):
    data = {"new_answer": ANSWER, "source_ids": ["current:synthetic:v1"],
            "recent_dialogue": [], "state": {}, "current_entries": [{
                "id": "old", "source_id": "entry:old:v1", "field_key": "present.wishes",
                "value": "担心儿子", "state": "filled", "certainty": "reported",
                "source": {"quote": "儿子住长沙"},
            }]}
    output = candidate(data)
    output["changes"][0].update(state="filled", certainty="reported", record_key="single")
    raw = inspection({"accepted_changes": output["changes"]})
    raw["question_claims"] = [{"claim": "担心儿子", "status": "supported",
                               "source_id": "entry:old:v1", "support_quote": "担心儿子"}]

    class Stub:
        def chat_json(self, *args):
            return raw

    assert quality.inspect(Stub(), output, data).question_claims[0].status == "unsupported"


def test_unknown_record_cannot_cover_known_fact(enabled):
    data = {"new_answer": ANSWER, "source_ids": ["current:synthetic:v1"],
            "recent_dialogue": [], "current_entries": [], "state": {}}
    output = candidate(data)
    output["changes"][0].update(state="unknown", certainty="reported", record_key="single")
    raw = inspection({"accepted_changes": output["changes"]})

    class Stub:
        def chat_json(self, *args):
            return raw

    checked = quality.inspect(Stub(), output, data)
    assert checked.facts[0].matches == []
    assert "unresolved_fact_match" in checked.match_issues


def test_extra_evidence_resolves_user_version_and_rejects_invented_source(enabled):
    data = {"new_answer": ANSWER, "source_ids": ["current:synthetic:v1"],
            "recent_dialogue": [{"id": "round:earlier:v2", "answer": "从2000年起散步。"}],
            "current_entries": [], "state": {}}
    output = candidate(data)
    output["changes"][0].update(state="filled", certainty="reported", record_key="single")
    raw = inspection({"accepted_changes": output["changes"]})
    raw["record_evidence"] = [
        {"change_index": 0, "source_id": "round:earlier:v2", "quote": "从2000年起散步。"},
        {"change_index": 0, "source_id": "round:invented:v1", "quote": "从2000年起散步。"},
    ]

    class Stub:
        def chat_json(self, *args):
            return raw

    checked = quality.inspect(Stub(), output, data)
    assert {"type": "interview_round", "id": "earlier", "version": 2,
            "quote": "从2000年起散步。"} in checked.verified_evidence[0]
    assert "invalid_record_evidence_source" in checked.match_issues


def test_completed_extraction_replay_uses_persisted_ledger(client, enabled, monkeypatch):
    calls = []

    def recorded(self, system, text):
        calls.append(system)
        return provider(self, system, text)

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", recorded)
    person = client.post("/v1/persons", json={"display_name": "重放合成人物"}).json()
    session = client.post("/v1/interviews", json={"subject_id": person["id"]}).json()
    request_id, round_id = uuid4(), uuid4()
    source = {"type": "interview_round", "id": str(round_id), "version": 1}
    with SessionLocal() as db:
        first = process(db, get_settings().default_tenant_id, UUID(session["profile_id"]),
                        ANSWER, source, request_id)
        count = len(calls)
        replay = process(db, get_settings().default_tenant_id, UUID(session["profile_id"]),
                         ANSWER, source, request_id)
    assert len(calls) == count
    assert replay["profile"]["version_number"] == first["profile"]["version_number"]
    assert replay["audit"]["fact_ledger"] == first["audit"]["fact_ledger"]


def test_consistent_dual_link_is_normalized_but_wrong_entry_is_not(enabled):
    data = {"new_answer": ANSWER, "source_ids": ["current:synthetic:v1"],
            "recent_dialogue": [], "state": {}, "current_entries": [{
                "id": "old", "field_key": "present.daily_life", "record_key": "single",
                "value": "早上散步", "state": "filled", "certainty": "reported",
            }]}
    output = candidate(data)
    output["changes"][0].update(state="filled", certainty="reported", record_key="single")
    raw = inspection({"accepted_changes": output["changes"]})
    raw["facts"][0]["matches"][0]["entry_id"] = "old"

    class Stub:
        def chat_json(self, *args):
            return raw

    checked = quality.inspect(Stub(), output, data)
    assert checked.facts[0].matches[0].change_index == 0
    assert checked.facts[0].matches[0].entry_id is None
    raw["facts"][0]["matches"][0]["entry_id"] = "another-person-entry"
    assert quality.inspect(Stub(), output, data).facts[0].matches == []


def test_multiple_goals_trigger_question_repair(client, enabled, monkeypatch):
    count = 0

    def goals(self, system, text):
        nonlocal count
        result = provider(self, system, text)
        if system == quality.INSPECT_PROMPT:
            count += 1
            result["question_goals"] = ["散步地点"] if count == 2 else [
                "散步地点", "子女联系内容",
            ]
        return result

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", goals)
    result, _ = run(client)
    assert result["audit"]["quality"]["repair_calls"] == 1
    assert result["audit"]["quality"]["question_goals"] == ["散步地点"]
    assert result["audit"]["quality"]["question_issues"] == []


def test_complex_turn_uses_two_sol_reviews_with_lite_record_audit(
    client, enabled, monkeypatch,
):
    calls = []

    def recorded(self, system, text):
        calls.append((self.model, system))
        return provider(self, system, text)

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", recorded)
    result, _ = run(client, ANSWER + "我1980年开始散步，1990年以后改为早上走。")
    assert ("synthetic-sol", quality.INSPECT_PROMPT) in calls
    assert ("synthetic-lite", companion.AUDIT_PROMPT) in calls
    assert calls.count(("synthetic-sol", quality.INSPECT_PROMPT)) == 2
    assert ("synthetic-lite", quality.REPAIR_PROMPT) in calls
    assert result["audit"]["quality"]["sync_assistance_calls"] == 2


def test_inventory_is_built_without_generated_candidates_or_questions(enabled):
    material = {"new_answer": ANSWER, "source_ids": ["current:synthetic:v1"],
                "recent_dialogue": [], "current_entries": [], "state": {}}

    class Stub:
        def chat_json(self, system, text):
            assert system == quality.INVENTORY_PROMPT
            data = json.loads(text)
            assert not {"accepted_changes", "next_question", "current_entries"} & data.keys()
            return {"facts": inspection({"accepted_changes": []})["facts"]}

    facts = quality.inventory(Stub(), material)
    assert [f["fact_id"] for f in facts] == [0, 1, 2, 3]
    assert all("matches" not in f for f in facts)


@pytest.mark.parametrize("role", ["answer_target", "generic_frame", "personal_assertion"])
def test_unknown_question_targets_and_specific_assertions_are_distinguished(role):
    checked = quality.Inspection.model_validate({
        "facts": [], "question_goals": ["了解是否学过手艺"],
        "question_claims": [{"claim": "学手艺", "role": role, "status": "unsupported"}],
        "question_issues": [{"kind": "presupposition", "claim_index": 0,
                             "detail": "还没披露学手艺"}],
    })
    assert bool(quality.question_problems(checked)) == (role == "personal_assertion")


def test_multiple_goal_issue_must_agree_with_independent_goal_list():
    checked = quality.Inspection.model_validate({
        "facts": [], "question_goals": ["一起生活的人"],
        "question_issues": [{"kind": "multiple_goals", "detail": "日常活动和人物"}],
    })
    assert quality.question_problems(checked) == []
    checked.question_goals.append("日常活动")
    assert quality.question_problems(checked)


def test_unmapped_personal_fact_stays_in_ledger_without_impossible_field_repair(
    client, enabled, monkeypatch,
):
    def unmapped(self, system, text):
        result = provider(self, system, text)
        if system in {quality.INVENTORY_PROMPT, quality.INSPECT_PROMPT}:
            result["facts"].append({"claim": "本人名为李棠", "quote": "我叫李棠。",
                                    "fields": [], "matches": []})
        return result

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", unmapped)
    result, _ = run(client, ANSWER + "我叫李棠。")
    assert result["audit"]["quality"]["pending_facts"] == 0
    assert result["audit"]["quality"]["unmapped_facts"] == 1
    assert result["audit"]["fact_ledger"][-1]["status"] == "unmapped"


def test_quality_audit_cannot_erase_program_departure_clarification(
    client, enabled, monkeypatch,
):
    def rejected_question(self, system, text):
        result = provider(self, system, text)
        if system == quality.INSPECT_PROMPT:
            result["question_claims"] = [{"claim": "父亲去世", "status": "unsupported"}]
        return result

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", rejected_question)
    result, _ = run(client, ANSWER + "我父亲是2019年去的。")
    assert result["next_question"] == companion.DEPARTURE_QUESTION
    assert result["audit"]["departure_clarification"] is True
    assert result["decision"]["action"] == "clarify"
    assert any(e["field_key"] == "present.daily_life" for e in result["profile"]["entries"])


def test_pending_context_deduplicates_and_excludes_superseded_answer_versions():
    def revision(version, status="pending"):
        return SimpleNamespace(changes=[{"metadata": {"interview_audit": {"fact_ledger": [{
            "id": f"current:answer:v{version}:fact:0", "claim": "时间",
            "status": status, "targets": [{"field": "work.records[]", "status": status}],
        }]}}}])

    assert quality.pending_records([revision(2, "covered"), revision(1)], {}) == []
    assert len(quality.pending_records([revision(2), revision(2), revision(1)], {})) == 1
    assert quality.pending_records([revision(1)], {"id": "answer", "version": 2}) == []


def test_question_quote_cannot_be_assembled_across_original_sources(enabled):
    material = {"new_answer": ANSWER, "source_ids": ["current:synthetic:v1"],
                "recent_dialogue": [], "state": {}, "current_entries": [{
                    "id": "old", "source_id": "entry:old:v1", "field_key": "present.daily_life",
                    "value": "散步", "state": "filled", "certainty": "reported",
                    "source": {"id": "a", "quote": "早晨散步。", "evidence": [
                        {"id": "b", "quote": "晚上休息。"},
                    ]},
                }]}
    output = candidate(material)
    output["changes"][0].update(state="filled", certainty="reported", record_key="single")
    raw = inspection({"accepted_changes": output["changes"]})
    raw["question_claims"] = [{"claim": "日常安排", "status": "supported",
                               "source_id": "entry:old:v1",
                               "support_quote": "早晨散步。\n晚上休息。"}]

    class Stub:
        def chat_json(self, *args):
            return raw

    assert quality.inspect(Stub(), output, material).question_claims[0].status == "unsupported"


@pytest.mark.parametrize("status", ["unknown", "not_required"])
@pytest.mark.parametrize("role", ["answer_target", "personal_assertion"])
def test_provider_unknown_status_never_authorizes_a_personal_assertion(enabled, status, role):
    material = {"new_answer": ANSWER, "source_ids": ["current:synthetic:v1"],
                "recent_dialogue": [], "current_entries": [], "state": {}}
    output = candidate(material)
    output["changes"][0].update(state="filled", certainty="reported", record_key="single")
    raw = inspection({"accepted_changes": output["changes"]})
    raw["question_claims"] = [{"claim": "学过手艺", "role": role, "status": status}]

    class Stub:
        def chat_json(self, *args):
            return raw

    checked = quality.inspect(Stub(), output, material)
    assert checked.question_claims[0].status == "unsupported"
    assert bool(quality.question_problems(checked)) == (role == "personal_assertion")


def test_recheck_failure_keeps_independently_audited_repair_without_paid_retry(
    client, enabled, monkeypatch,
):
    calls = 0

    def failing(self, system, text):
        nonlocal calls
        if self.model == "synthetic-sol" and system == quality.INSPECT_PROMPT:
            calls += 1
            raise httpx.ReadTimeout("synthetic")
        return provider(self, system, text)

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", failing)
    result, _ = run(client)
    assert calls == 1
    assert result["audit"]["quality"]["status"] == "partial"
    assert result["audit"]["quality"]["recovered_changes"] == 1
    assert any(e["field_key"] == "present.relationships" for e in result["profile"]["entries"])


def test_audited_date_correction_does_not_replace_neighboring_event_year(
    client, enabled, monkeypatch,
):
    person = client.post("/v1/persons", json={"display_name": "多事件更正"}).json()
    session = client.post("/v1/interviews", json={"subject_id": person["id"]}).json()
    initial = "1999年文化站撤并，1999年转到县图书馆。"
    corrected = "转到县图书馆的年份更正为2000年，不是1999年；1999年是文化站撤并。"
    entry_id = None

    def audited(self, prompt, material):
        is_correction = material["new_answer"] == corrected
        change = {"field_key": "work.records[]", "record_key": "transfer",
                  "value": {"what": "1999年文化站撤并，2000年转到县图书馆。"
                            if is_correction else initial,
                            "time_raw": "2000年" if is_correction else "1999年"},
                  "quote": material["new_answer"]}
        if is_correction:
            change["id"] = entry_id
        return {"changes": [change], "next_question": "您想继续讲哪段经历？",
                "decision": {"action": "transition", "used_source_ids": [
                    material["source_ids"][0]], "question_goal": "继续采访"}}, {"verdict": "pass"}

    monkeypatch.setattr(companion, "generate", audited)
    with SessionLocal() as db:
        first = process(db, get_settings().default_tenant_id, UUID(session["profile_id"]), initial,
                        {"type": "interview_round", "id": str(uuid4()), "version": 1}, uuid4())
        entry_id = next(e["id"] for e in first["profile"]["entries"]
                        if e["field_key"] == "work.records[]")
        final = process(
            db, get_settings().default_tenant_id, UUID(session["profile_id"]), corrected,
            {"type": "interview_round", "id": str(uuid4()), "version": 1}, uuid4(),
        )
    saved = next(e for e in final["profile"]["entries"] if e["id"] == entry_id)
    assert saved["value"]["what"] == "1999年文化站撤并，2000年转到县图书馆。"
    assert saved["value"]["time_raw"] == "2000年"


@pytest.mark.parametrize("role", ["answer_target", "personal_assertion"])
def test_nullable_question_evidence_does_not_authorize_assertions(enabled, role):
    material = {"new_answer": ANSWER, "source_ids": ["current:synthetic:v1"],
                "recent_dialogue": [], "current_entries": [], "state": {}}
    output = candidate(material)
    output["changes"][0].update(state="filled", certainty="reported", record_key="single")
    raw = inspection({"accepted_changes": output["changes"]})
    raw["question_claims"] = [{"claim": "学过手艺", "role": role, "status": "supported",
                               "source_id": None, "support_quote": None}]

    class Stub:
        def chat_json(self, *args):
            return raw

    checked = quality.inspect(Stub(), output, material)
    assert checked.question_claims[0].status == "unsupported"
    assert checked.question_claims[0].source_id == checked.question_claims[0].support_quote == ""
    assert bool(quality.question_problems(checked)) == (role == "personal_assertion")


@pytest.mark.parametrize("failure", ["schema", "timeout"])
def test_initial_inspection_failure_retains_frozen_pending_inventory(
    client, enabled, monkeypatch, failure,
):
    inspections = 0

    def failing(self, system, text):
        nonlocal inspections
        if system == quality.INSPECT_PROMPT:
            inspections += 1
            if failure == "timeout":
                raise httpx.ReadTimeout("synthetic")
            return {"facts": "invalid"}
        return provider(self, system, text)

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", failing)
    result, _ = run(client)
    assert inspections == 1
    assert len(result["audit"]["fact_ledger"]) == 4
    assert all(f["status"] == "pending" for f in result["audit"]["fact_ledger"])
    report = result["audit"]["quality"]
    assert report["status"] == "unverified" and report["pending_facts"] == 4
    if failure == "schema":
        assert report["validation_issues"] == [{"loc": ["facts"], "type": "list_type"}]
    assert any(e["field_key"] == "present.daily_life" for e in result["profile"]["entries"])


def test_known_review_format_failure_recovers_only_independently_audited_facts(
    client, enabled, monkeypatch,
):
    audits = 0
    repairs = 0

    def recovering(self, system, text):
        nonlocal audits, repairs
        data = json.loads(text)
        if system == companion.AUDIT_PROMPT:
            audits += 1
            if audits <= 2:
                return {"verdict": "pass", "safe_change_indices": [99], "issues": []}
            return provider(self, system, text)
        if system == quality.REPAIR_PROMPT:
            repairs += 1
            assert len(data["missing_facts"]) == 4
            return {"changes": candidate(data)["changes"] + [{
                "field_key": "present.relationships", "value": RELATIONS, "quote": RELATIONS,
            }], "next_question": "您和孩子联系时，通常会聊些什么？",
                    "decision": {"action": "deepen_scene", "question_goal": "了解联系内容",
                                 "used_source_ids": [data["source_ids"][0]]}}
        return provider(self, system, text)

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", recovering)
    result, _ = run(client)
    assert audits == 3 and repairs == 1
    assert result["audit"]["rejection_reason"] == "invalid_review_indices"
    assert result["audit"]["quality_fact_only_recovery"]
    assert result["audit"]["verdict"] == "clarify" and result["audit"]["reply_fallback"]
    assert result["next_question"] == companion.fallback()
    assert result["audit"]["quality"]["pending_facts"] == 0
    assert any(e["field_key"] == "present.relationships" for e in result["profile"]["entries"])


def test_uncertain_main_audit_does_not_start_paid_fact_recovery(client, enabled, monkeypatch):
    calls = []

    def uncertain(self, system, text):
        calls.append(system)
        if system == companion.AUDIT_PROMPT:
            raise httpx.ReadTimeout("synthetic")
        return provider(self, system, text)

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", uncertain)
    result, _ = run(client)
    assert result["audit"]["transport_uncertain"]
    assert result["audit"]["verdict"] == "fallback"
    assert quality.INVENTORY_PROMPT not in calls and quality.REPAIR_PROMPT not in calls
    assert not result["audit"].get("quality_fact_only_recovery")


@pytest.mark.parametrize("target", ["父亲", "爸爸", "弟弟", "母亲"])
@pytest.mark.parametrize("role_key", ["role", "relationship"])
def test_departure_continuation_stays_with_original_relative(enabled, target, role_key):
    material = {"new_answer": "去的是佛山，在我弟弟家住，不是去世。他现在还活着，"
                              "1936年出生的是他，不是我。",
                "source_ids": ["current:synthetic:v1"], "current_entries": [],
                "recent_questions": [], "recent_dialogue": [{
                    "answer": "我父亲是2018年去的。", "question": "请您澄清去的意思？",
                }]}
    change = {"field_key": "family.members[]", "record_key": "new",
              "value": {role_key: target, "birth_time_raw": "1936", "status": "仍健在"},
              "quote": material["new_answer"], "state": "filled"}
    output = {**candidate(material), "changes": [change]}
    invalid = {}
    _, issues = companion.program_issues(output, material, invalid_changes=invalid)
    assert ("departure_family_misattribution" in issues) == (target not in {"父亲", "爸爸"})
    assert bool(invalid) == (target not in {"父亲", "爸爸"})


def test_departure_guard_checks_linked_sibling_and_allows_explicit_new_facts(enabled):
    material = {"new_answer": "去的是佛山，在我弟弟家住，不是去世。他1936年出生。"
                              "我弟弟1980年出生，在长沙工作。",
                "source_ids": ["current:synthetic:v1"], "recent_questions": [],
                "recent_dialogue": [{"answer": "我爸爸是2018年去的。", "question": "去了哪里？"}],
                "current_entries": [{"id": "brother", "field_key": "family.members[]",
                                     "record_key": "sibling", "value": {"role": "弟弟"}}]}
    change = {"id": "brother", "field_key": "family.members[]", "record_key": "other",
              "value": {"role": "父亲", "birth_time_raw": "1936年"}}
    assert companion.departure_family_misattribution(change, material)
    change["value"] = {"role": "弟弟", "birth_time_raw": "1980年", "work": "长沙工作"}
    assert not companion.departure_family_misattribution(change, material)
    change["value"] = {"role": "弟弟", "birth_time_raw": "1936年"}
    material["new_answer"] += "我弟弟也是1936年出生。"
    assert not companion.departure_family_misattribution(change, material)
    material["recent_dialogue"][0]["answer"] = "父亲和弟弟2018年去了佛山。"
    assert not companion.departure_family_misattribution(change, material)


@pytest.mark.parametrize("repair_role", ["父亲", "弟弟"])
def test_family_guard_applies_to_main_generation_and_quality_repair(
    client, enabled, monkeypatch, repair_role,
):
    answer = "去的是佛山，在我弟弟家住，不是去世。他现在还活着，1936年出生的是他，不是我。"
    previous = {"id": "round:previous:v1", "answer": "我父亲是2018年去的。",
                "question": companion.DEPARTURE_QUESTION}
    monkeypatch.setattr(companion, "dialogue_context", lambda *args: (
        None, {"state": {}, "recent_dialogue": [previous]},
    ))

    def family_change(role):
        return {"field_key": "family.members[]", "record_key": "new",
                "value": {"role": role, "birth_time_raw": "1936年", "status": "仍健在"},
                "quote": answer}

    def family_provider(self, system, text):
        data = json.loads(text)
        if system == companion.AUDIT_PROMPT:
            return {"verdict": "pass", "safe_change_indices": list(
                range(len(data["candidate"]["changes"]))), "issues": []}
        fact = {"fact_id": 0, "claim": "父亲1936年出生，仍健在", "quote": answer,
                "fields": ["family.members[]"], "matches": []}
        if system == quality.INVENTORY_PROMPT:
            return {"facts": [fact]}
        if system == quality.INSPECT_PROMPT:
            fact["matches"] = [{"field": "family.members[]", "change_index": c["index"]}
                               for c in data["accepted_changes"]
                               if c["value"]["role"] == "父亲"]
            return {"facts": [fact]}
        if system == quality.REPAIR_PROMPT:
            return {"changes": [family_change(repair_role)], "next_question": None,
                    "decision": None}
        return {**candidate(data), "changes": [family_change("弟弟")],
                "next_question": "您想接着讲哪段经历？"}

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", family_provider)
    result, _ = run(client, answer)
    family = [e for e in result["profile"]["entries"] if e["field_key"] == "family.members[]"]
    assert all(e["value"]["role"] == "父亲" for e in family)
    assert bool(family) == (repair_role == "父亲")
    assert result["audit"]["quality"]["pending_facts"] == (0 if family else 1)
    assert any("departure_family_misattribution" in c["issues"]
               for c in result["audit"]["rejected_candidates"] if c["stage"] == "program")


def test_dropping_relative_move_preserves_audited_father_when_reply_needs_rewrite(
    client, enabled, monkeypatch,
):
    monkeypatch.setattr(enabled, "interview_quality_enabled", False)
    answer = "去的是长沙，在我弟弟家住，不是去世了。父亲现在还活着，1938年出生的是他，不是我。"
    audits = 0
    monkeypatch.setattr(companion, "dialogue_context", lambda *args: (
        None, {"state": {}, "recent_dialogue": [{"id": "round:previous:v1",
                "answer": "我父亲是2008年去的。", "question": companion.DEPARTURE_QUESTION}]},
    ))

    def partial(self, system, text):
        nonlocal audits
        data = json.loads(text)
        if system == companion.AUDIT_PROMPT:
            audits += 1
            return {"verdict": "pass" if audits == 1 else "rewrite",
                    "safe_change_indices": [0, 1] if audits == 1 else [0],
                    "issues": [] if audits == 1 else ["问题错误地把父亲的搬迁问成本人经历"]}
        return {**candidate(data), "next_question": "您2008年为什么去长沙住？", "changes": [
            {"field_key": "family.members[]", "record_key": "new",
             "value": {"relationship": "父亲", "detail": "1938年出生，现在还活着"},
             "quote": "父亲现在还活着，1938年出生的是他，不是我。"},
            {"field_key": "turning.moves[]", "record_key": "new",
             "value": {"what": "去了长沙，在弟弟家住", "time_raw": "2008年"},
             "quote": "去的是长沙，在我弟弟家住，不是去世了。"},
        ]}

    monkeypatch.setattr(OpenAICompatibleClient, "chat_json", partial)
    result, _ = run(client, answer)
    family = [e for e in result["profile"]["entries"] if e["field_key"] == "family.members[]"]
    assert audits == 2 and len(family) == 1
    assert family[0]["value"]["relationship"] == "父亲"
    assert not any(e["field_key"] == "turning.moves[]" for e in result["profile"]["entries"])
    assert result["audit"]["verdict"] == "clarify" and result["audit"]["reply_fallback"]

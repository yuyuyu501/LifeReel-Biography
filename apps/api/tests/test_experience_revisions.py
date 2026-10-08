from uuid import UUID

from sqlalchemy import select

from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.interview.models import InterviewRound
from lifereel_api.modules.interview.planning import control, repeated
from lifereel_api.modules.memory.models import MemoryClaim, MemoryConflict, TimelineAnchor


def start(client):
    person = client.post("/v1/persons", json={"display_name": "体验回归"}).json()
    chapter = client.get("/v1/chapters").json()[0]
    return client.post(
        "/v1/interviews",
        json={
            "mode": "legacy",
            "subject_id": person["id"],
            "chapter_id": chapter["id"],
        },
    ).json()


def test_answer_revision_updates_sources_and_keeps_original(client):
    session = start(client)
    url = f"/v1/interviews/{session['id']}/turns"
    round_id = session["rounds"][0]["id"]
    first = client.post(
        url,
        json={
            "round_id": round_id,
            "answer_text": "1998年我在杭州读书。",
            "idempotency_key": "experience-original",
        },
    )
    assert first.status_code == 202, first.text
    payload = {
        "action": "revise_answer",
        "round_id": round_id,
        "expected_version": 1,
        "answer_text": "1989年我在湖州读书，母亲每天送我上学。",
        "idempotency_key": "experience-revision",
    }
    revised = client.post(url, json=payload)
    assert revised.status_code == 202, revised.text
    assert revised.json()["status"] == "completed"
    with SessionLocal() as db:
        answer = db.get(InterviewRound, UUID(round_id))
        assert answer.answer_version == 2
        assert answer.answer_revisions[0]["text"] == "1998年我在杭州读书。"
        claim = db.scalar(select(MemoryClaim).where(MemoryClaim.source_round_id == answer.id))
        assert claim.source_revision == 2
        assert claim.source_quote == payload["answer_text"]
        anchors = list(
            db.scalars(select(TimelineAnchor).where(TimelineAnchor.claim_id == claim.id))
        )
        assert anchors and all(a.year != 1998 for a in anchors)
    replay = client.post(url, json=payload)
    assert replay.json()["id"] == revised.json()["id"]
    stale = client.post(url, json={**payload, "idempotency_key": "experience-stale"})
    assert stale.status_code == 409
    altered = client.post(url, json={**payload, "answer_text": "1980年我在北京。"})
    assert altered.status_code == 409
    workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert workspace["progress"]["stage"] == "completed"
    assert workspace["progress"]["estimated_seconds"] is None
    assert workspace["latest_workflow"]["script_brief"]["response_completed_at"]


def test_revision_requires_explicit_version_and_legacy_cannot_bypass(client):
    session = start(client)
    round_id = session["rounds"][0]["id"]
    url = f"/v1/interviews/{session['id']}/turns"
    response = client.post(
        url,
        json={
            "round_id": round_id,
            "answer_text": "我在家乡长大。",
            "idempotency_key": "boundary-original",
        },
    )
    assert response.status_code == 202
    assert (
        client.post(
            url,
            json={
                "action": "revise_answer",
                "round_id": round_id,
                "answer_text": "新的内容",
                "idempotency_key": "missing-version",
            },
        ).status_code
        == 422
    )
    old_route = f"/v1/interviews/{session['id']}/rounds/{round_id}/answer"
    assert client.post(old_route, json={"answer_text": "偷偷修改"}).status_code == 409


def test_pause_does_not_create_new_facts_or_generate_script(client):
    session = start(client)
    response = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={
            "answer_text": "先不聊了",
            "idempotency_key": "pause-experience",
        },
    )
    assert response.status_code == 202, response.text
    result = response.json()
    assert "之后可以继续" in result["next_question"]
    assert result["script_project_id"] is None
    with SessionLocal() as db:
        assert not list(db.scalars(select(MemoryClaim)))


def test_planner_control_and_rephrased_duplicate():
    assert control("今天先不聊了。") == "pause"
    assert control("母亲说不想说，但我还想继续") == "continue"
    assert control("这个不想说了") == "skip"
    assert repeated("你能讲讲当时的工作环境吗？", ["您能讲讲当时的工作环境吗？"])
    assert not repeated("第一次上工是谁带您的？", ["您当时在哪个城市工作？"])


def test_revision_closes_only_conflicts_using_old_source(client):
    session = start(client)
    url = f"/v1/interviews/{session['id']}/turns"
    round_id = session["rounds"][0]["id"]
    client.post(
        url,
        json={
            "round_id": round_id,
            "answer_text": "1998年我在杭州读书。",
            "idempotency_key": "conflict-original",
        },
    )
    with SessionLocal() as db:
        claim = db.scalar(select(MemoryClaim).where(MemoryClaim.source_round_id == UUID(round_id)))
        old = MemoryConflict(
            tenant_id=claim.tenant_id,
            subject_id=claim.subject_id,
            claim_ids=[str(claim.id)],
            conflict_key="school_year",
            description="旧来源年份冲突",
        )
        unrelated = MemoryConflict(
            tenant_id=claim.tenant_id,
            subject_id=claim.subject_id,
            claim_ids=[],
            conflict_key="other",
            description="其他资料仍需核对",
        )
        db.add_all([old, unrelated])
        db.commit()
        old_id, other_id = old.id, unrelated.id
    response = client.post(
        url,
        json={
            "action": "revise_answer",
            "round_id": round_id,
            "answer_text": "1989年我在湖州读书。",
            "expected_version": 1,
            "idempotency_key": "conflict-revision",
        },
    )
    assert response.status_code == 202
    with SessionLocal() as db:
        assert db.get(MemoryConflict, old_id).status == "superseded"
        assert db.get(MemoryConflict, other_id).status == "open"


def test_pause_skips_paid_skills_and_is_not_imported_by_next_turn(client, monkeypatch):
    from lifereel_api.modules.orchestration.skills import ScriptSkill

    session = start(client)
    original = ScriptSkill.assess
    monkeypatch.setattr(
        ScriptSkill,
        "assess",
        lambda *args: (_ for _ in ()).throw(AssertionError("pause called AI")),
    )
    url = f"/v1/interviews/{session['id']}/turns"
    response = client.post(
        url, json={"answer_text": "先不聊了", "idempotency_key": "no-paid-pause"}
    )
    assert response.status_code == 202, response.text
    monkeypatch.setattr(ScriptSkill, "assess", original)
    response = client.post(
        url, json={"answer_text": "1992年我来到广州。", "idempotency_key": "resume-pause"}
    )
    assert response.status_code == 202, response.text
    with SessionLocal() as db:
        assert all("不聊了" not in c.claim_text for c in db.scalars(select(MemoryClaim)))


def test_queued_correction_hides_stale_claims_before_extraction(client, monkeypatch):
    from lifereel_api.core.config import get_settings
    from lifereel_api.modules.jobs import service as jobs
    from lifereel_api.modules.memory import service as memory

    session = start(client)
    url = f"/v1/interviews/{session['id']}/turns"
    round_id = session["rounds"][0]["id"]
    assert (
        client.post(
            url,
            json={
                "round_id": round_id,
                "answer_text": "1998年我去杭州读书。",
                "idempotency_key": "queued-before",
            },
        ).status_code
        == 202
    )
    monkeypatch.setattr(get_settings(), "execute_mock_jobs_inline", False)
    monkeypatch.setattr(jobs, "enqueue", lambda _: None)
    response = client.post(
        url,
        json={
            "action": "revise_answer",
            "round_id": round_id,
            "expected_version": 1,
            "answer_text": "1989年我在湖州读书。",
            "idempotency_key": "queued-revision",
        },
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    with SessionLocal() as db:
        subject = UUID(session["subject_id"])
        tenant = get_settings().default_tenant_id
        assert memory.list_claims(db, tenant, subject) == []
        assert memory.list_timeline(db, tenant, subject) == []
    done = client.post(f"/v1/internal/interview-turns/{response.json()['id']}/execute")
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"


def test_transcript_revision_supersedes_previously_extracted_audio_claim(client):
    import pytest

    from lifereel_api.core.errors import ApiError
    from lifereel_api.modules.evidence.models import EvidenceObservation, SourceAsset
    from lifereel_api.modules.memory import service as memory

    session = start(client)
    url = f"/v1/interviews/{session['id']}/turns"
    round_id = session["rounds"][0]["id"]
    original = "1998年我去杭州读书。"
    assert (
        client.post(
            url,
            json={
                "round_id": round_id,
                "answer_text": original,
                "idempotency_key": "audio-original",
            },
        ).status_code
        == 202
    )
    with SessionLocal() as db:
        answer = db.get(InterviewRound, UUID(round_id))
        source = SourceAsset(
            tenant_id=answer.tenant_id,
            subject_id=UUID(session["subject_id"]),
            interview_session_id=answer.session_id,
            kind="audio",
            original_filename="qa.wav",
            mime_type="audio/wav",
            byte_size=10,
            sha256="a" * 64,
            storage_key="qa/audio-source",
        )
        db.add(source)
        db.flush()
        observation = EvidenceObservation(
            tenant_id=answer.tenant_id,
            subject_id=source.subject_id,
            source_asset_id=source.id,
            version_number=1,
            analysis_kind="asr",
            text=original,
        )
        db.add(observation)
        db.flush()
        old = MemoryClaim(
            tenant_id=answer.tenant_id,
            subject_id=source.subject_id,
            source_observation_id=observation.id,
            claim_text=original,
            source_quote=original,
        )
        db.add(old)
        answer.source_asset_id = source.id
        db.commit()
        old_id, source_id = old.id, source.id
    revised = client.post(
        url,
        json={
            "action": "revise_answer",
            "round_id": round_id,
            "expected_version": 1,
            "answer_text": "1989年我在湖州读书。",
            "idempotency_key": "audio-revised",
        },
    )
    assert revised.status_code == 202, revised.text
    with SessionLocal() as db:
        old = db.get(MemoryClaim, old_id)
        assert old.review_status == "superseded"
        assert db.get(InterviewRound, UUID(round_id)).source_asset_id == source_id
        assert old.id not in [c.id for c in memory.list_claims(db, old.tenant_id, old.subject_id)]
        with pytest.raises(ApiError):
            memory.review_claim(db, old.tenant_id, old_id, "verified")

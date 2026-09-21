from io import BytesIO
from uuid import UUID

import pytest
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.evidence.models import EvidenceObservation, TranscriptVersion
from lifereel_api.modules.interview import service as interviews
from lifereel_api.modules.interview.models import InterviewRound, InterviewTurnWorkflow
from lifereel_api.modules.interview.schemas import InterviewAnswer, InterviewTurnCreate
from lifereel_api.modules.orchestration import service as orchestration


def _start(client):
    person = client.post("/v1/persons", json={"display_name": "Input boundary"}).json()
    session = client.post("/v1/interviews", json={"subject_id": person["id"]}).json()
    return person, session


@pytest.mark.parametrize("endpoint", ["turn", "answer"])
@pytest.mark.parametrize("size", [20_001, 50_001])
def test_long_answer_is_rejected_before_saving_and_same_round_accepts_short_turn(client, endpoint,
                                                                              size):
    _, session = _start(client)
    round_id = session["rounds"][0]["id"]
    workspace_url = f"/v1/interviews/{session['id']}/workspace"
    before = client.get(workspace_url).json()
    wallet = client.get("/v1/wallet").json()
    jobs = client.get("/v1/jobs").json()
    path = (f"/v1/interviews/{session['id']}/turns" if endpoint == "turn" else
            f"/v1/interviews/{session['id']}/rounds/{round_id}/answer")
    rejected = client.post(path, json={
        "round_id": round_id, "answer_text": "家" * size,
        "idempotency_key": "same-key-after-rejection",
    })
    assert rejected.status_code == 413
    assert rejected.json()["error"]["code"] == "MEMORY_INPUT_TOO_LARGE"
    assert rejected.json()["error"]["context"]["limit_chars"] == 20_000
    assert client.get(workspace_url).json() == before
    assert client.get("/v1/wallet").json() == wallet
    assert client.get("/v1/jobs").json() == jobs
    submitted = client.post(f"/v1/interviews/{session['id']}/turns", json={
        "round_id": round_id, "answer_text": "母亲在家教我读书。",
        "idempotency_key": "same-key-after-rejection",
    })
    assert submitted.status_code == 202
    assert submitted.json()["status"] == "completed"
    after = client.get(workspace_url).json()
    assert after["session"]["rounds"][0]["answer_text"] == "母亲在家教我读书。"


@pytest.mark.parametrize("schema", [InterviewAnswer, InterviewTurnCreate])
def test_exact_twenty_thousand_character_answer_is_accepted_by_input_contract(schema):
    payload = schema.model_validate({
        "answer_text": "家" * 20_000, "idempotency_key": "at-input-boundary",
    })
    assert len(payload.answer_text) == 20_000


@pytest.mark.parametrize("entry", ["answer", "turn"])
def test_internal_write_entry_also_rejects_oversized_answer(client, entry):
    _, session = _start(client)
    round_id = UUID(session["rounds"][0]["id"])
    with SessionLocal() as db:
        round_ = db.get(InterviewRound, round_id)
        with pytest.raises(ApiError) as exc:
            if entry == "answer":
                interviews.answer_round(db, round_.tenant_id, round_.session_id, round_.id,
                                        "家" * 20_001)
            else:
                # model_construct simulates an internal caller bypassing HTTP validation.
                orchestration.create_turn(db, round_.tenant_id, round_.session_id,
                                          InterviewTurnCreate.model_construct(
                                              answer_text="家" * 20_001,
                                              idempotency_key="internal-long-answer",
                                          ))
        assert exc.value.code == ErrorCode.MEMORY_INPUT_TOO_LARGE
        assert not round_.answer_text
        assert db.scalar(select(InterviewTurnWorkflow)) is None


@pytest.mark.parametrize("kind,mime,content", [
    ("audio", "audio/ogg", b"OggSsynthetic-audio"),
    ("video", "video/mp4", b"\x00\x00\x00\x18ftypisomsynthetic-video"),
])
def test_long_media_transcript_is_preserved_without_poisoning_next_short_answer(
    client, monkeypatch, tmp_path, kind, mime, content,
):
    monkeypatch.setattr(get_settings(), "local_storage_path", str(tmp_path / "storage"))
    person, session = _start(client)
    asset = client.post(
        "/v1/evidence/assets",
        data={"subject_id": person["id"], "interview_session_id": session["id"], "kind": kind},
        files={"file": ("recording", BytesIO(content), mime)},
    )
    assert asset.status_code == 201
    asset_id = asset.json()["id"]
    original = "家" * 20_001
    transcript = client.post(f"/v1/evidence/assets/{asset_id}/transcript",
                             json={"text": original, "source": "manual"})
    assert transcript.status_code == 201
    rejected = client.post(f"/v1/interviews/{session['id']}/turns", json={
        "asset_ids": [asset_id], "idempotency_key": "oversized-media-input",
    })
    assert rejected.status_code == 413
    assert rejected.json()["error"]["code"] == "MEMORY_INPUT_TOO_LARGE"
    assert rejected.json()["error"]["context"]["original_preserved"] is True
    with SessionLocal() as db:
        assert db.scalar(select(TranscriptVersion)).text == original
        assert db.scalar(select(EvidenceObservation)) is None
        assert not db.get(InterviewRound, UUID(session["rounds"][0]["id"])).answer_text
    workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert workspace["latest_workflow"]["retry_allowed"] is False
    continued = client.post(f"/v1/interviews/{session['id']}/turns", json={
        "answer_text": "小时候母亲在家教我读书。", "idempotency_key": "short-after-media",
    })
    assert continued.status_code == 202
    assert continued.json()["status"] == "completed"
    assert continued.json()["asset_ids"] == []
    assert client.get(f"/v1/evidence/assets/{asset_id}/content").content == content


def test_raised_document_extraction_budget_does_not_persist_unusable_observation(
    client, monkeypatch, tmp_path,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "document_extract_max_chars", 30_000)
    person, session = _start(client)
    text = "家" * 20_001
    uploaded = client.post(
        "/v1/evidence/assets", data={"subject_id": person["id"], "kind": "document"},
        files={"file": ("large.txt", BytesIO(text.encode()), "text/plain")},
    )
    assert uploaded.status_code == 201
    asset_id = uploaded.json()["id"]
    rejected = client.post(f"/v1/interviews/{session['id']}/turns", json={
        "asset_ids": [asset_id], "idempotency_key": "larger-extraction-limit",
    })
    assert rejected.status_code == 413
    assert rejected.json()["error"]["code"] == "MEMORY_INPUT_TOO_LARGE"
    with SessionLocal() as db:
        assert db.scalar(select(EvidenceObservation)) is None
    continued = client.post(f"/v1/interviews/{session['id']}/turns", json={
        "answer_text": "母亲在家教我读书。", "idempotency_key": "short-after-document",
    })
    assert continued.status_code == 202
    assert continued.json()["status"] == "completed"
    assert client.get(f"/v1/evidence/assets/{asset_id}/content").content == text.encode()

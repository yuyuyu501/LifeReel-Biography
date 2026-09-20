from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from starlette.websockets import WebSocketDisconnect

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError
from lifereel_api.core.models import utcnow
from lifereel_api.modules.interview import voice_service as service
from lifereel_api.modules.interview.models import InterviewTurnWorkflow, InterviewVoiceCall
from lifereel_api.providers import realtime_voice as provider

ORIGIN = {"origin": "http://localhost:5173"}


@pytest.fixture
def voice(client, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "realtime_voice_provider", "mock")
    monkeypatch.setattr(get_settings(), "local_storage_path", str(tmp_path))
    monkeypatch.setattr(get_settings(), "job_queue_backend", "database")
    person = client.post("/v1/persons", json={"display_name": "语音测试"}).json()
    chapter = client.get("/v1/chapters").json()[0]
    session = client.post(
        "/v1/interviews",
        json={
            "subject_id": person["id"],
            "chapter_id": chapter["id"],
        },
    ).json()
    response = client.post(f"/v1/interviews/{session['id']}/voice")
    assert response.status_code == 201
    return session, response.json()


def receive_until(socket, kind):
    events = []
    for _ in range(30):
        event = socket.receive_json()
        events.append(event)
        if event["type"] == kind:
            return event, events
    raise AssertionError(f"Missing {kind}")


def test_call_updates_graph_and_script_before_hangup_without_saving_conversation(
    client, voice, tmp_path, monkeypatch,
):
    from lifereel_api.modules.evidence.models import SourceAsset
    from lifereel_api.modules.jobs.models import Job
    from lifereel_api.modules.memory import service as memory
    from lifereel_api.modules.memory.models import MemoryClaim, MemoryEntity

    monkeypatch.setattr(memory, "_extract_claim", lambda *_a, **_kw: (
        "童年与母亲共同生活在村里。", "recollection", 0.9, "test-extractor", None,
    ))
    session, call = voice
    with client.websocket_connect(f"/v1/interview-voice/{call['id']}/stream", headers=ORIGIN) as ws:
        receive_until(ws, "ready")
        ws.send_bytes(bytes(640))
        update, events = receive_until(ws, "update.done")
        assert update["memory_updated"] and update["script_updated"]
        # The update is observable while the voice connection is still active.
        workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
        assert workspace["script"]["scenes"]
        assert not any(r["answer_text"] for r in workspace["session"]["rounds"])
        assert workspace["latest_workflow"] is None
        with SessionLocal() as db:
            stored_call = db.get(InterviewVoiceCall, UUID(call["id"]))
            assert stored_call.status == "active" and stored_call.messages == []
            claim = db.scalar(select(MemoryClaim))
            assert claim.claim_text == "童年与母亲共同生活在村里。"
            assert claim.source_quote == "" and claim.source_round_id is None
            assert db.scalar(select(func.count()).select_from(MemoryEntity)) > 0
            assert db.scalar(select(func.count()).select_from(Job)) == 0
        ws.send_json({"type": "mute", "muted": True})
        ws.send_json({"type": "mute", "muted": False})
        ws.send_json({"type": "end"})
        result, _ = receive_until(ws, "ended")
    assert result["call"]["status"] == "completed"
    assert result["call"]["messages"] == []
    assert result["call"]["source_asset_id"] is None
    assert result["call"]["workflow_id"] is None
    assert any(e["type"] == "transcript.done" and e["role"] == "user" for e in events)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SourceAsset)) == 0
        assert db.scalar(select(func.count()).select_from(InterviewTurnWorkflow)) == 0
        from lifereel_api.core.database import Base

        for table in Base.metadata.sorted_tables:
            assert "小时候我和母亲住在村里。" not in str(db.execute(select(table)).all())
    assert not list(tmp_path.rglob("*"))
    repeated = service.finish(get_settings().default_tenant_id, UUID(call["id"]))
    assert repeated["workflow_id"] is None


def test_busy_blocks_text_calls_and_manual_rounds(client, voice):
    session, _ = voice
    path = f"/v1/interviews/{session['id']}"
    assert client.post(path + "/voice").status_code == 409
    assert (
        client.post(
            path + "/turns",
            json={
                "answer_text": "不应同时提交",
                "idempotency_key": "competing-voice-turn",
            },
        ).status_code
        == 409
    )
    assert client.post(path + "/rounds", json={"question_text": "另一个问题"}).status_code == 409
    assert client.get(path + "/next-question").status_code == 409
    assert (
        client.post(
            path + f"/rounds/{session['rounds'][0]['id']}/answer",
            json={"answer_text": "另一个答案"},
        ).status_code
        == 409
    )


def test_provider_protocol_is_current_json_and_pcm16(monkeypatch):
    monkeypatch.setattr(get_settings(), "doubao_realtime_api_key", "never-send-to-browser")
    event = provider.session_event("test-id", "本章采访背景")
    assert event["session"]["model"] == "1.2.6.1"
    assert event["session"]["audio"]["output"]["format"] == {"type": "pcm_s16le", "rate": 24000}
    assert "extension" in event and "extension" not in event["session"]
    assert "never-send-to-browser" not in str(event)


def test_only_user_utterances_update_memory_and_duplicates_are_ignored(client, voice, monkeypatch):
    from lifereel_api.modules.memory.models import MemoryClaim

    session, call = voice
    @asynccontextmanager
    async def connection():
        mock = provider.MockConnection()
        original_send = mock.send

        async def send(event):
            await original_send(event)
            if event["type"] == "input_audio_buffer.append":
                await mock.events.put({
                    "type": provider.ASR_PREFIX + "completed",
                    "item_id": "user-1", "transcript": "重复原文不得再次执行。",
                })
                await mock.events.put({
                    "type": "response.output_text.done", "response_id": "assistant-extra",
                    "text": "我猜您在北京。",
                })
        mock.send = send
        yield mock

    monkeypatch.setattr(provider, "open_connection", connection)
    with client.websocket_connect(f"/v1/interview-voice/{call['id']}/stream", headers=ORIGIN) as ws:
        receive_until(ws, "ready")
        ws.send_bytes(bytes(640))
        receive_until(ws, "update.done")
        ws.send_json({"type": "end"})
        result, _ = receive_until(ws, "ended")
    assert result["call"]["messages"] == []
    with SessionLocal() as db:
        claims = list(db.scalars(select(MemoryClaim)))
        assert len(claims) == 1 and "北京" not in claims[0].claim_text
        assert claims[0].source_quote == ""
    workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert not any(r["answer_text"] for r in workspace["session"]["rounds"])


def test_stale_call_recovery_does_not_create_transcript_or_deferred_work(client, voice):
    _, call = voice
    tenant = get_settings().default_tenant_id
    call_id = UUID(call["id"])
    service.attach(tenant, None, call_id)
    with SessionLocal() as db:
        db.get(InterviewVoiceCall, call_id).heartbeat_at = utcnow() - timedelta(seconds=90)
        db.commit()
    service.recover_stale()
    service.recover_stale()
    with SessionLocal() as db:
        result = db.get(InterviewVoiceCall, call_id)
        assert result.status == "interrupted"
        assert result.workflow_id is None and result.messages == []
        assert db.scalar(select(func.count()).select_from(InterviewTurnWorkflow)) == 0


def test_live_call_not_recovered_by_old_lease_snapshot(client, voice):
    _, call = voice
    result = service.finish(get_settings().default_tenant_id, UUID(call["id"]), stale_only=True)
    assert result["status"] == "connecting"


@pytest.mark.parametrize("origin", [None, "https://untrusted.example"])
def test_websocket_rejects_foreign_or_absent_origin(client, voice, origin):
    _, call = voice
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/v1/interview-voice/{call['id']}/stream", headers={"origin": origin} if origin else {}
        ):
            pass


def test_socket_cannot_reconnect_or_access_other_tenant(client, voice):
    _, call = voice
    tenant = get_settings().default_tenant_id
    service.attach(tenant, None, UUID(call["id"]))
    with pytest.raises(ApiError):
        service.attach(tenant, None, UUID(call["id"]))
    with pytest.raises(ApiError):
        service.attach(uuid4(), None, UUID(call["id"]))


def test_provider_failure_finishes_call_without_leaking_error(client, voice, monkeypatch):
    _, call = voice

    @asynccontextmanager
    async def fail():
        raise RuntimeError("secret-provider-credential")
        yield

    monkeypatch.setattr(provider, "open_connection", fail)
    with client.websocket_connect(f"/v1/interview-voice/{call['id']}/stream", headers=ORIGIN) as ws:
        result, _ = receive_until(ws, "ended")
    assert result["call"]["error_code"] == "VOICE_CONNECTION_FAILED"
    assert "secret-provider" not in str(result)
    assert not result["call"]["workflow_id"]


def test_disabled_provider_and_production_mock_are_unavailable(client, monkeypatch):
    assert not service.enabled()
    monkeypatch.setattr(get_settings(), "realtime_voice_provider", "mock")
    monkeypatch.setattr(get_settings(), "app_env", "production")
    assert not service.enabled()


def test_bad_audio_frame_is_rejected_without_new_answers(client, voice):
    _, call = voice
    with client.websocket_connect(f"/v1/interview-voice/{call['id']}/stream", headers=ORIGIN) as ws:
        receive_until(ws, "ready")
        ws.send_bytes(bytes(2048))
        result, _ = receive_until(ws, "ended")
    assert result["call"]["error_code"] == "VOICE_PROTOCOL_INVALID"
    assert result["call"]["workflow_id"] is None


@pytest.mark.parametrize("role,active", [("viewer", True), ("owner", False)])
def test_readonly_or_revoked_account_cannot_join(client, voice, monkeypatch, role, active):
    from lifereel_api.modules.auth.models import TenantMembership, UserAccount
    from lifereel_api.modules.auth.security import create_token

    session, call = voice
    monkeypatch.setattr(get_settings(), "auth_token_secret", "test-only-voice-secret")
    with SessionLocal() as db:
        user = UserAccount(display_name="Voice test", password_hash="unused", is_active=active)
        db.add(user)
        db.flush()
        db.add(
            TenantMembership(user_id=user.id, tenant_id=get_settings().default_tenant_id, role=role)
        )
        db.get(InterviewVoiceCall, UUID(call["id"])).user_id = user.id
        db.commit()
        token = create_token(
            {"sub": str(user.id), "tenant_id": str(get_settings().default_tenant_id)}
        )
    client.cookies.set("lifereel_session", token)
    assert client.post(f"/v1/interviews/{session['id']}/voice").status_code in (401, 403)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/v1/interview-voice/{call['id']}/stream", headers=ORIGIN):
            pass


def test_old_workflow_retry_is_blocked_during_call(client, voice):
    from lifereel_api.modules.jobs.models import Job

    session, _ = voice
    tenant = get_settings().default_tenant_id
    with SessionLocal() as db:
        job = Job(
            tenant_id=tenant,
            kind="interview.turn.process",
            status="failed",
            payload={},
            idempotency_key="old-voice-workflow",
        )
        db.add(job)
        db.flush()
        db.add(
            InterviewTurnWorkflow(
                tenant_id=tenant,
                session_id=UUID(session["id"]),
                round_id=UUID(session["rounds"][0]["id"]),
                job_id=job.id,
                idempotency_key="old-voice-workflow",
                status="failed",
            )
        )
        db.commit()
        job_id = str(job.id)
    response = client.post(f"/v1/jobs/{job_id}/retry")
    assert response.status_code == 409
    assert "VOICE_CALL_BUSY" in response.text


def test_voice_migration_preserves_existing_schema(tmp_path):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    from lifereel_api.core.database import Base

    migration_path = Path(__file__).parents[1] / "alembic/versions/20260918_0030_interview_voice.py"
    spec = importlib.util.spec_from_file_location("voice_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'voice-migration.db'}")
    Base.metadata.create_all(
        engine, tables=[t for t in Base.metadata.sorted_tables if t.name != "interview_voice_calls"]
    )
    before = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            columns = {
                column["name"]
                for column in inspect(connection).get_columns("interview_voice_calls")
            }
            assert columns == set(InterviewVoiceCall.__table__.columns.keys())
            migration.downgrade()
            assert set(inspect(connection).get_table_names()) == before
            migration.upgrade()
    engine.dispose()

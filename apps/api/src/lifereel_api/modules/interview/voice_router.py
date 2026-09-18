from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import wave
from contextlib import suppress
from tempfile import TemporaryFile
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal, get_db
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.core.security import require_api_access
from lifereel_api.modules.auth.dependencies import AuthContext, auth_context
from lifereel_api.modules.interview import service as interviews
from lifereel_api.modules.interview import voice_service as service
from lifereel_api.modules.interview.models import InterviewVoiceCall
from lifereel_api.providers import realtime_voice as provider

logger = logging.getLogger(__name__)
router = APIRouter(tags=["interview-voice"])
socket_router = APIRouter()
Db = Annotated[Session, Depends(get_db)]
Auth = Annotated[AuthContext, Depends(auth_context)]


@router.get("/interviews/{session_id}/voice")
def state(session_id: UUID, db: Db, context: Auth):
    interviews.get_session(db, context.tenant_id, session_id)
    call = db.scalar(
        select(InterviewVoiceCall)
        .where(
            InterviewVoiceCall.tenant_id == context.tenant_id,
            InterviewVoiceCall.session_id == session_id,
        )
        .order_by(InterviewVoiceCall.started_at.desc())
        .limit(1)
    )
    return {
        "enabled": service.enabled() and context.role in {"owner", "editor", "worker"},
        "max_seconds": get_settings().realtime_voice_max_seconds,
        "call": service.payload(call) if call else None,
    }


@router.post("/interviews/{session_id}/voice", status_code=201)
def start(session_id: UUID, db: Db, context: Auth):
    return service.payload(service.start(db, context, session_id))


def authenticate(socket: WebSocket) -> AuthContext:
    settings = get_settings()
    # Browser cookies require explicit cross-site WebSocket protection.
    origin = socket.headers.get("origin", "")
    if origin not in settings.api_cors_origins:
        raise ApiError(403, ErrorCode.AUTH_REQUIRED)
    require_api_access(socket, socket.headers.get("x-api-key"))
    with SessionLocal() as db:
        context = auth_context(
            socket,
            db,
            None,
            None,
            socket.cookies.get("lifereel_session"),
        )
        if context.role not in {"owner", "editor"}:
            raise ApiError(403, ErrorCode.AUTH_READ_ONLY)
        return context


@socket_router.websocket("/v1/interview-voice/{call_id}/stream")
async def stream(socket: WebSocket, call_id: UUID):
    attached = False
    context = None
    error_code = None
    disconnected = False
    tasks = []
    audio_bytes = 0
    recording = TemporaryFile()
    wav = wave.open(recording, "wb")
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(16000)
    send_lock = asyncio.Lock()

    async def send(event: dict):
        nonlocal disconnected
        if disconnected:
            return
        try:
            async with send_lock:
                await asyncio.wait_for(socket.send_json(jsonable_encoder(event)), timeout=5)
        except (WebSocketDisconnect, RuntimeError, OSError):
            disconnected = True

    try:
        context = await run_in_threadpool(authenticate, socket)
        if not service.enabled():
            raise ApiError(503, ErrorCode.VOICE_NOT_CONFIGURED)
        instructions, greeting = await run_in_threadpool(
            service.attach,
            context.tenant_id,
            context.user_id,
            call_id,
        )
        attached = True
        await socket.accept()
        async with provider.open_connection() as upstream:
            await upstream.send(provider.session_event(str(call_id), instructions))
            async with asyncio.timeout(15):
                while True:
                    event = await upstream.receive()
                    if event.get("type") == "session.created":
                        break
                    if event.get("type") == "error":
                        raise ApiError(502, ErrorCode.VOICE_CONNECTION_FAILED)
            await send({"type": "ready", "call_id": str(call_id)})
            await upstream.send(
                {"type": "speech_text_buffer.commit", "speech_id": str(uuid4()), "text": greeting}
            )
            started = time.monotonic()
            ending = asyncio.Event()

            async def browser_audio():
                nonlocal audio_bytes, disconnected
                muted = False
                controls = 0
                window_start = time.monotonic()
                while True:
                    message = await asyncio.wait_for(socket.receive(), timeout=30)
                    if message["type"] == "websocket.disconnect":
                        disconnected = True
                        ending.set()
                        return
                    data = message.get("bytes")
                    if data is not None:
                        if muted:
                            continue
                        if len(data) != 640:
                            raise ApiError(400, ErrorCode.VOICE_PROTOCOL_INVALID)
                        audio_bytes += len(data)
                        if audio_bytes > (time.monotonic() - started + 2) * 32000:
                            raise ApiError(429, ErrorCode.VOICE_LIMIT_REACHED)
                        wav.writeframesraw(data)
                        await upstream.send(
                            {
                                "type": "input_audio_buffer.append",
                                "audio": base64.b64encode(data).decode("ascii"),
                            }
                        )
                        continue
                    raw = message.get("text", "")
                    if len(raw) > 1024:
                        raise ApiError(400, ErrorCode.VOICE_PROTOCOL_INVALID)
                    command = json.loads(raw)
                    if not isinstance(command, dict):
                        raise ApiError(400, ErrorCode.VOICE_PROTOCOL_INVALID)
                    if time.monotonic() - window_start > 10:
                        controls, window_start = 0, time.monotonic()
                    controls += 1
                    if controls > 40:
                        raise ApiError(429, ErrorCode.VOICE_LIMIT_REACHED)
                    kind = command.get("type")
                    if kind == "end":
                        ending.set()
                        return
                    if kind == "ping":
                        await send({"type": "pong"})
                    elif kind == "mute" and type(command.get("muted")) is bool:
                        muted = command["muted"]
                        await upstream.send(
                            {
                                "type": "input_audio_mute.commit"
                                if muted
                                else "input_audio_unmute.commit"
                            }
                        )
                    elif kind == "interrupt":
                        await upstream.send({"type": "response.cancel"})
                        await send({"type": "interrupted"})
                    else:
                        raise ApiError(400, ErrorCode.VOICE_PROTOCOL_INVALID)

            async def provider_events():
                while True:
                    event = await upstream.receive()
                    kind = event.get("type", "")
                    if kind == "session.closed":
                        return
                    if kind == "error":
                        raise ApiError(502, ErrorCode.VOICE_CONNECTION_FAILED)
                    if kind in {provider.ASR_PREFIX + "started", "response.canceled"}:
                        await send({"type": "interrupted"})
                    elif kind in {provider.ASR_PREFIX + "delta", "response.output_text.delta"}:
                        role = "user" if kind.startswith(provider.ASR_PREFIX) else "assistant"
                        await send(
                            {
                                "type": "transcript.delta",
                                "role": role,
                                "id": event.get("item_id") or event.get("response_id"),
                                "text": str(event.get("delta") or "")[:12000],
                            }
                        )
                    elif kind in {provider.ASR_PREFIX + "completed", "response.output_text.done"}:
                        role = "user" if kind.startswith(provider.ASR_PREFIX) else "assistant"
                        item_id = event.get("item_id") or event.get("response_id")
                        if not isinstance(item_id, str) or not item_id:
                            raise ApiError(502, ErrorCode.VOICE_PROTOCOL_INVALID)
                        text = event.get("transcript") or event.get("text") or ""
                        if not isinstance(text, str):
                            raise ApiError(502, ErrorCode.VOICE_PROTOCOL_INVALID)
                        await run_in_threadpool(
                            service.save_message,
                            context.tenant_id,
                            call_id,
                            f"{role}:{item_id}",
                            role,
                            text,
                        )
                        await send(
                            {"type": "transcript.done", "role": role, "id": item_id, "text": text}
                        )
                    elif kind == provider.ASR_PREFIX + "failed":
                        await send({"type": "transcript.failed"})
                    elif kind == "response.output_audio.started":
                        await send({"type": "audio.started", "id": event.get("response_id")})
                    elif kind == "response.output_audio.delta":
                        await send(
                            {
                                "type": "audio",
                                "id": event.get("response_id"),
                                "audio": event.get("delta") or "",
                            }
                        )
                    elif kind == "response.output_audio.done":
                        await send({"type": "audio.done"})
                    elif kind == "response.done":
                        await run_in_threadpool(
                            service.save_usage, context.tenant_id, call_id, event
                        )

            async def monitor():
                while True:
                    await asyncio.sleep(10)
                    renewed = await run_in_threadpool(authenticate, socket)
                    if renewed != context or not await run_in_threadpool(
                        service.touch,
                        context.tenant_id,
                        call_id,
                    ):
                        raise ApiError(401, ErrorCode.AUTH_SESSION_INACTIVE)
                    if time.monotonic() - started >= get_settings().realtime_voice_max_seconds:
                        await send({"type": "limit"})
                        ending.set()
                        return

            sender = asyncio.create_task(browser_audio())
            receiver = asyncio.create_task(provider_events())
            watcher = asyncio.create_task(monitor())
            ended = asyncio.create_task(ending.wait())
            tasks = [sender, receiver, watcher, ended]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            if disconnected or (receiver in done and not ending.is_set()):
                error_code = ErrorCode.VOICE_CONNECTION_FAILED
            if not receiver.done():
                # Flush the final utterance before requesting a graceful provider close.
                sender.cancel()
                await upstream.send({"type": "input_audio_buffer.commit"})
                await upstream.send({"type": "input_audio_mute.commit"})
                await asyncio.sleep(0.5)
                await upstream.send({"type": "session.close"})
                await asyncio.wait_for(asyncio.shield(receiver), timeout=8)
    except ApiError as exc:
        error_code = str(exc.code)
    except asyncio.CancelledError:
        error_code = ErrorCode.VOICE_CONNECTION_FAILED
        raise
    except Exception as exc:
        # Provider exceptions can contain auth headers or private transcripts.
        logger.warning("Voice call ended: %s", type(exc).__name__)
        error_code = ErrorCode.VOICE_CONNECTION_FAILED
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        wav.close()
        if attached and context:
            if audio_bytes:
                try:
                    await run_in_threadpool(
                        service.save_recording, context.tenant_id, call_id, recording
                    )
                except Exception as exc:
                    logger.error("Voice recording save failed: %s", type(exc).__name__)
                    error_code = error_code or "VOICE_RECORDING_FAILED"
            try:
                result = await run_in_threadpool(
                    service.finish, context.tenant_id, call_id, error_code
                )
                await send({"type": "ended", "call": result})
            except Exception as exc:
                logger.error("Voice finalization failed: %s", type(exc).__name__)
                await send({"type": "error", "code": "VOICE_SAVE_PENDING"})
        recording.close()
        with suppress(RuntimeError, OSError):
            await socket.close(code=1000 if attached else 1008)

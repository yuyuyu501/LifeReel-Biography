"""Doubao full-duplex JSON protocol. Credentials never reach the browser."""

from __future__ import annotations

import asyncio
import base64
import json
from contextlib import asynccontextmanager
from uuid import uuid4

from websockets.asyncio.client import connect

from lifereel_api.core.config import get_settings
from lifereel_api.modules.orchestration.skills import voice_tools

ENDPOINT = "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"
MODEL = "1.2.6.1"
ASR_PREFIX = "conversation.item.input_audio_transcription."


def session_event(call_id: str, instructions: str) -> dict:
    return {
        "type": "session.create",
        "event_id": str(uuid4()),
        "session": {
            "id": call_id,
            "model": MODEL,
            "instructions": instructions,
            "audio": {
                "input": {"format": {"type": "pcm", "rate": 16000}},
                "output": {
                    "format": {"type": "pcm_s16le", "rate": 24000},
                    "voice": get_settings().doubao_realtime_voice,
                },
            },
            "tools": voice_tools(),
        },
        "extension": {
            "asr": {"extra": {}},
            "tts": {"extra": {}},
            "dialog": {"extra": {"enable_music": False, "enable_loudness_norm": True}},
        },
    }


def tool_result_event(results: list[tuple[str, dict]]) -> dict:
    """Seeduplex FC result format (not OpenAI's function_call_output format)."""
    return {
        "type": "conversation.item.create", "event_id": str(uuid4()),
        "items": [{"call_id": call_id, "role": "tool", "content": [
            {"type": "input_text", "text": json.dumps(result, ensure_ascii=False)},
        ]} for call_id, result in results],
    }


class DoubaoConnection:
    def __init__(self, socket):
        self.socket = socket

    async def send(self, event: dict):
        await self.socket.send(json.dumps(event, ensure_ascii=False))

    async def receive(self) -> dict:
        event = json.loads(await self.socket.recv())
        if not isinstance(event, dict):
            raise ValueError("Invalid provider event")
        return event


class MockConnection:
    """Deterministic development transport, never selected in production."""

    def __init__(self):
        self.events = asyncio.Queue()
        self.audio_received = False
        self.turn = 0

    async def send(self, event: dict):
        kind = event["type"]
        if kind == "session.create":
            await self.events.put({"type": "session.created"})
        elif kind == "speech_text_buffer.commit":
            await self.events.put(
                {
                    "type": "response.output_text.done",
                    "response_id": "greeting",
                    "text": event["text"],
                }
            )
        elif kind == "input_audio_buffer.append":
            if not self.audio_received:
                await self.events.put({"type": ASR_PREFIX + "started", "item_id": "mock-user"})
                self.turn += 1
                await self.events.put(
                    {
                        "type": ASR_PREFIX + "completed",
                        "item_id": f"user-{self.turn}",
                        "transcript": "小时候我和母亲住在村里。",
                    }
                )
                await self.events.put(
                    {
                        "type": "response.output_text.done",
                        "response_id": f"reply-{self.turn}",
                        "text": "您最记得和母亲一起做什么？",
                    }
                )
                await self.events.put(
                    {
                        "type": "response.output_audio.delta",
                        "delta": base64.b64encode(bytes(960)).decode(),
                    }
                )
                self.audio_received = True
        elif kind in {"input_audio_buffer.commit", "session.close"}:
            if kind == "session.close":
                await self.events.put({"type": "session.closed"})

    async def receive(self) -> dict:
        return await self.events.get()


@asynccontextmanager
async def open_connection():
    settings = get_settings()
    if settings.realtime_voice_provider == "mock" and settings.is_development:
        yield MockConnection()
        return
    async with connect(
        ENDPOINT,
        additional_headers={"X-Api-Key": settings.doubao_realtime_api_key or ""},
        open_timeout=15,
        close_timeout=3,
        ping_interval=20,
        ping_timeout=20,
        max_size=2 * 1024 * 1024,
        max_queue=16,
    ) as socket:
        yield DoubaoConnection(socket)

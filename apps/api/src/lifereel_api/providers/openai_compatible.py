from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

from lifereel_api.modules.billing.usage import record
from lifereel_api.providers.base import ProviderCapabilities


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="openai-compatible",
            kinds=("llm", "asr"),
            configured=bool(self.base_url and self.api_key and self.model),
        )

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _chat(self, messages: list[dict[str, Any]], json_output: bool = False) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.4,
            "messages": messages,
        }
        if json_output:
            payload["response_format"] = {"type": "json_object"}
        started = time.monotonic()
        data = {}
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={**self.headers, "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except Exception as exc:
            record(
                self.model,
                "failed",
                data.get("usage") or {},
                int((time.monotonic() - started) * 1000),
                error=type(exc).__name__,
            )
            raise
        record(
            self.model,
            "succeeded",
            data.get("usage") or {},
            int((time.monotonic() - started) * 1000),
            data.get("id"),
        )
        return content

    def chat(self, system: str, user: str) -> str:
        return self._chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )

    def chat_json(self, system: str, user: str) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            content = self._chat(messages, json_output=True).strip()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            content = self._chat(messages).strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
        return json.loads(fenced.group(1) if fenced else content)

    def analyze_images(self, system: str, prompt: str, images: list[tuple[str, bytes]]) -> str:
        import base64

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for mime_type, data in images:
            encoded = base64.b64encode(data).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded}", "detail": "low"},
                }
            )
        return self._chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ]
        )

    def transcribe(self, filename: str, content: bytes, mime_type: str) -> str:
        started = time.monotonic()
        try:
            response = httpx.post(
                f"{self.base_url}/audio/transcriptions",
                headers=self.headers,
                data={"model": self.model},
                files={"file": (Path(filename).name, content, mime_type)},
                timeout=180,
            )
            response.raise_for_status()
            result = response.json()
            text = result["text"]
        except Exception as exc:
            record(
                self.model,
                "failed",
                {},
                int((time.monotonic() - started) * 1000),
                error=type(exc).__name__,
            )
            raise
        record(
            self.model,
            "succeeded",
            result.get("usage") or {},
            int((time.monotonic() - started) * 1000),
            result.get("id"),
        )
        return text

    @staticmethod
    def idempotency_key(content: bytes, model: str) -> str:
        return hashlib.sha256(content + model.encode()).hexdigest()

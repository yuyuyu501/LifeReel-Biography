from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

from lifereel_api.core.capacity import limited
from lifereel_api.core.config import LLMTask, get_settings
from lifereel_api.modules.billing import tokens
from lifereel_api.modules.billing.usage import current_context, record
from lifereel_api.providers.base import ProviderCapabilities

logger = logging.getLogger(__name__)
TASKS: dict[str, LLMTask] = {
    "question": "interview", "interview": "interview", "memory": "memory",
    "script": "script", "evidence": "vision", "vision": "vision",
    "video": "video_plan", "video_plan": "video_plan",
}


class ProviderResponseError(json.JSONDecodeError):
    """Compatible with callers' JSON validation handling, without retaining private output."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code, "", 0)


class ProviderHTTPError(httpx.HTTPStatusError):
    response_format_unsupported = False


class ProviderStreamError(httpx.RemoteProtocolError):
    """Incomplete streams are uncertain transport, never schema-correction retries."""


def _read_stream(response: httpx.Response, data: dict, max_seconds: float) -> None:
    content: list[str] = []
    event: list[str] = []
    finished = done = False
    started = time.monotonic()

    def lines():
        total = 0
        pending = b""
        for block in response.iter_bytes():
            total += len(block)
            if total > 2_000_000 or time.monotonic() - started > max_seconds:
                raise ProviderStreamError("LLM_STREAM_LIMIT_EXCEEDED")
            pending += block
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                try:
                    yield line.rstrip(b"\r").decode("utf-8")
                except UnicodeDecodeError:
                    raise ProviderStreamError("LLM_STREAM_ENCODING_INVALID") from None
        if pending:
            try:
                yield pending.rstrip(b"\r").decode("utf-8")
            except UnicodeDecodeError:
                raise ProviderStreamError("LLM_STREAM_ENCODING_INVALID") from None

    def consume() -> bool:
        nonlocal finished
        text = "\n".join(event)
        event.clear()
        if text.strip() == "[DONE]":
            return True
        try:
            chunk = json.loads(text)
        except ValueError:
            raise ProviderStreamError("LLM_STREAM_EVENT_INVALID") from None
        if not isinstance(chunk, dict):
            raise ProviderStreamError("LLM_STREAM_EVENT_INVALID")
        # Retain receipts even if a later event is invalid/incomplete.
        if chunk.get("usage") is not None:
            data["usage"] = chunk["usage"]
        if "id" in chunk:
            data["id"] = chunk["id"]
        if "error" in chunk:
            raise ProviderStreamError("LLM_STREAM_PROVIDER_ERROR")
        choices = chunk.get("choices")
        if not isinstance(choices, list):
            raise ProviderStreamError("LLM_STREAM_CHOICES_INVALID")
        for choice in choices:
            if not isinstance(choice, dict) or choice.get("index") != 0:
                raise ProviderStreamError("LLM_STREAM_CHOICE_INVALID")
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                raise ProviderStreamError("LLM_STREAM_DELTA_INVALID")
            piece = delta.get("content")
            if piece is not None:
                if not isinstance(piece, str) or finished:
                    raise ProviderStreamError("LLM_STREAM_CONTENT_INVALID")
                content.append(piece)
            if choice.get("finish_reason") is not None:
                finished = True
        return False

    for line in lines():
        if not line:
            if event and consume():
                done = True
                break
        elif line.startswith("data:"):
            event.append(line[5:].lstrip(" "))
        # SSE comments/other fields are not model output.
    if not done and event:
        done = consume()
    if not done or not finished:
        raise ProviderStreamError("LLM_STREAM_INCOMPLETE")
    data["choices"] = [{"message": {"content": "".join(content)}}]


def _unsupported_response_format(data: dict) -> bool:
    """Only explicit capability rejection allows one request without JSON mode."""
    error = data.get("error")
    if not isinstance(error, dict):
        return False
    code = str(error.get("code", "")).lower()
    param = str(error.get("param", "")).lower()
    message = str(error.get("message", "")).lower()
    if param in {"response_format", "response_format.type"} and code in {
        "unsupported_parameter", "unsupported_value", "not_supported",
    }:
        return True
    # Do not match e.g. "unsupported model; response_format must be JSON".
    return bool(re.search(
        r"(?:response_format|json_object)[\s'\"`]*(?:is\s+)?(?:not supported|unsupported)"
        r"|(?:does not support|doesn't support|unsupported|unrecognized request argument"
        r"|unknown parameter)[\s:'\"`]+(?:the\s+)?(?:parameter\s+)?"
        r"[\s'\"`]*(?:response_format|json_object)\b",
        message,
    ))


def _usage(data: dict) -> dict:
    # Preserve the original receipt, including unsupported categories and invalid values.
    # Dropping/coercing fields can turn an unpriceable receipt into a billable one.
    # Usage is retained for audit/settlement, never included in diagnostic logs.
    receipt = data.get("usage")
    return receipt if isinstance(receipt, dict) else {}


class OpenAICompatibleClient:
    def __init__(
        self, base_url: str, api_key: str, model: str, *, task: LLMTask | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.task = task

    def _task(self) -> LLMTask:
        context = current_context()
        return self.task or TASKS.get(context[1] if context else "", "interview")

    def _request_id(self, value: Any) -> str | None:
        if (
            isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", value)
            and not (self.api_key and self.api_key in value)
        ):
            return value
        return None

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="openai-compatible",
            kinds=("llm", "asr"),
            configured=bool(self.base_url and self.api_key and self.model),
        )

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    @limited("llm")
    def _chat(
        self, messages: list[dict[str, Any]], json_output: bool = False,
        *, parse_json: bool = False, task: LLMTask | None = None,
    ) -> Any:
        task = task or self._task()
        timeout = httpx.Timeout(**get_settings().llm_timeouts_for(task))
        stream = get_settings().llm_stream_for(task)
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.4,
            "messages": messages,
        }
        if json_output:
            payload["response_format"] = {"type": "json_object"}
        if stream:
            payload.update(stream=True, stream_options={"include_usage": True})
        reservation = tokens.begin(self.base_url, self.model, current_context())
        if reservation or (tokens.enabled() and current_context()):
            payload["max_tokens"] = tokens.MAX_OUTPUT
        started = time.monotonic()
        data = {}
        response = None
        request_id = None
        receipt_id = None
        diagnostic: dict[str, Any] = {"task": task}
        try:
            request = {
                "headers": {**self.headers, "Content-Type": "application/json"},
                "json": payload, "timeout": timeout,
            }
            if stream:
                with httpx.stream(
                    "POST", f"{self.base_url}/chat/completions", **request,
                ) as response:
                    if response.is_success:
                        _read_stream(response, data, get_settings().llm_stream_max_seconds)
                    else:
                        body = bytearray()
                        # Error pages can also be huge/endless. Keep HTTP status even if
                        # the bounded body cannot be parsed; never print its contents.
                        for block in response.iter_bytes():
                            if (len(body) + len(block) > 2_000_000
                                    or time.monotonic() - started
                                    > get_settings().llm_stream_max_seconds):
                                body.clear()
                                break
                            body.extend(block)
                        try:
                            data = json.loads(body)
                        except (ValueError, UnicodeDecodeError):
                            data = {}
            else:
                response = httpx.post(f"{self.base_url}/chat/completions", **request)
            diagnostic["http_status"] = response.status_code
            for header in ("x-request-id", "request-id", "x-ms-request-id", "x-tt-logid"):
                request_id = self._request_id(response.headers.get(header))
                if request_id:
                    break
            if not stream:
                try:
                    data = response.json()
                except ValueError:
                    data = {}
            if not isinstance(data, dict):
                data = {}
            receipt_id = self._request_id(data.get("id"))
            request_id = request_id or receipt_id
            diagnostic["request_id"] = request_id
            if not response.is_success:
                error = ProviderHTTPError(
                    f"LLM_HTTP_ERROR status={response.status_code} request_id={request_id}",
                    request=response.request, response=response,
                )
                error.response_format_unsupported = (
                    response.status_code == 400 and _unsupported_response_format(data)
                )
                raise error
            if not data:
                raise ProviderResponseError("LLM_RESPONSE_NOT_JSON_OBJECT")
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ProviderResponseError("LLM_RESPONSE_CHOICES_INVALID")
            message = choices[0].get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str) or not content.strip():
                raise ProviderResponseError("LLM_RESPONSE_CONTENT_INVALID")
            if parse_json:
                content = content.strip()
                fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
                try:
                    content = json.loads(fenced.group(1) if fenced else content)
                except ValueError:
                    raise ProviderResponseError("LLM_OUTPUT_JSON_INVALID") from None
                if not isinstance(content, dict):
                    raise ProviderResponseError("LLM_OUTPUT_NOT_OBJECT")
        except Exception as exc:
            # Streaming can fail after headers or a receipt, before the common parser.
            if response is not None:
                diagnostic["http_status"] = response.status_code
                receipt_id = self._request_id(data.get("id"))
                for header in ("x-request-id", "request-id", "x-ms-request-id", "x-tt-logid"):
                    request_id = request_id or self._request_id(response.headers.get(header))
                request_id = request_id or receipt_id
                diagnostic["request_id"] = request_id
            code = getattr(exc, "code", type(exc).__name__)
            if isinstance(exc, ProviderStreamError):
                code = str(exc)  # Only fixed internal codes are constructed above.
            diagnostic["error"] = code
            if isinstance(exc, httpx.TimeoutException):
                diagnostic["phase"] = {
                    httpx.ConnectTimeout: "connect", httpx.ReadTimeout: "read",
                    httpx.WriteTimeout: "write", httpx.PoolTimeout: "pool",
                }.get(type(exc), "unknown")
            # No exc_info: upstream exceptions can include URLs, body text or credentials.
            logger.warning("llm.request_failed %s", json.dumps(diagnostic, sort_keys=True))
            record(
                self.model,
                "failed",
                _usage(data),
                int((time.monotonic() - started) * 1000),
                request_id=receipt_id or request_id,
                error=f"{code}:{response.status_code}" if response is not None else code,
                reservation=reservation,
                rejected=response is not None
                and response.status_code
                in {
                    400,
                    401,
                    403,
                    404,
                    413,
                    422,
                    429,
                },
            )
            if isinstance(exc, httpx.RequestError):
                # Keep timeout classes for callers, but suppress unsafe upstream exception text.
                safe_error = type(exc)(f"LLM_REQUEST_FAILED {type(exc).__name__}")
                safe_error.diagnostic = diagnostic
                raise safe_error from None
            exc.diagnostic = diagnostic
            raise
        record(
            self.model,
            "succeeded",
            _usage(data),
            int((time.monotonic() - started) * 1000),
            receipt_id or request_id,
            reservation=reservation,
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
            return self._chat(messages, json_output=True, parse_json=True)
        except ProviderHTTPError as exc:
            if not exc.response_format_unsupported:
                raise
        return self._chat(messages, parse_json=True)

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
            ],
            task="vision",
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

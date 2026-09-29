import re
from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.providers import seedream, siliconflow
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient
from lifereel_api.providers.rpc import decode_bytes, encode_bytes

CALLERS = {"interview", "worker-interview", "memory", "script", "media", "worker-media"}


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ChatPayload(Payload):
    task: Literal["interview", "memory", "script", "vision", "video_plan"]
    model: str = Field(min_length=1, max_length=200)
    messages: list[dict] = Field(min_length=1, max_length=1000)
    json_output: bool
    parse_json: bool


class AudioPayload(Payload):
    key: str
    filename: str
    mime_type: str
    model: str = ""
    backend: Literal["whisper", "openai"]
    hotwords: str | None = None


class ImagePayload(Payload):
    provider: Literal["seedream", "siliconflow"]
    content: str
    mime_type: str
    prompt: str
    size: str = "2K"


class VideoArguments(Payload):
    body: dict | None = Field(default=None, alias="json")


class VideoPayload(Payload):
    method: Literal["GET", "POST"]
    path: str
    arguments: VideoArguments = Field(default_factory=VideoArguments)


class GenericPayload(Payload):
    name: str
    kind: str
    action: Literal["submit", "status", "cancel", "outputs"]
    request: dict | None = None
    idempotency_key: str | None = None
    job_id: str | None = None


def validate(operation, data):
    schema = {
        "llm.chat": ChatPayload,
        "model.audio": AudioPayload,
        "model.image": ImagePayload,
        "model.video-request": VideoPayload,
        "model.generic": GenericPayload,
    }[operation]
    result = schema.model_validate(data).model_dump(exclude_none=True, by_alias=True)
    if operation == "model.generic":
        if result["action"] == "submit":
            if not result.get("request") or not result.get("idempotency_key"):
                raise ValueError("INVALID_SUBMISSION")
        elif not result.get("job_id"):
            raise ValueError("MISSING_JOB")
    return result


def chat(db, tenant, data):
    settings = get_settings()
    task = data["task"]
    if task not in {"interview", "memory", "script", "vision", "video_plan"}:
        raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)
    model = settings.model_for(task)
    if data["model"] != model or settings.llm_provider != "openai-compatible":
        raise ApiError(503, ErrorCode.INTERVIEW_LLM_CONFIGURATION_INCOMPLETE)
    client = OpenAICompatibleClient(
        settings.openai_compatible_base_url or "",
        settings.openai_compatible_api_key or "",
        model,
        task=task,
    )
    return {
        "output": client._chat(
            data["messages"],
            json_output=data["json_output"],
            parse_json=data["parse_json"],
            task=task,
        )
    }


def audio(db, tenant, data):
    from lifereel_api.modules.evidence.storage import private_storage

    settings = get_settings()
    key = data["key"]
    if not re.fullmatch(
        r"service-transit/" + re.escape(str(tenant)) + r"/[0-9a-f-]{36}\.audio", key
    ):
        raise ApiError(403, ErrorCode.AUTH_READ_ONLY)
    content = private_storage().get(key)
    if data["backend"] == "whisper":
        if settings.asr_provider != "faster-whisper":
            raise ApiError(503, ErrorCode.SERVICE_UNAVAILABLE)
        from lifereel_api.providers.whisper import FasterWhisperClient

        client = FasterWhisperClient(
            settings.whisper_model_path or settings.model_for("asr"),
            settings.whisper_device,
            settings.whisper_compute_type,
            hotwords=data.get("hotwords"),
        )
    else:
        if data["model"] != settings.model_for("asr"):
            raise ApiError(503, ErrorCode.SERVICE_UNAVAILABLE)
        client = OpenAICompatibleClient(
            settings.openai_compatible_base_url or "",
            settings.openai_compatible_api_key or "",
            data["model"],
        )
    return {"text": client.transcribe(data["filename"], content, data["mime_type"])}


def image_edit(db, tenant, data):
    provider = data["provider"]
    content = decode_bytes(data["content"])
    if provider == "seedream":
        result = seedream.edit(content, data["mime_type"], prompt=data["prompt"], size=data["size"])
    elif provider == "siliconflow":
        result = siliconflow.edit(content, data["mime_type"], prompt=data["prompt"])
    else:
        raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)
    return {
        "content": encode_bytes(result.content),
        "mime_type": result.mime_type,
        "trace_id": result.trace_id,
    }


def video_request(db, tenant, data):
    from lifereel_api.providers.video import VolcengineSeedanceProvider

    method, path = data["method"], data["path"]
    valid = (method == "POST" and path == "/contents/generations/tasks") or (
        method == "GET" and re.fullmatch(r"/contents/generations/tasks/[A-Za-z0-9_-]{1,200}", path)
    )
    if not valid:
        raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)
    client = VolcengineSeedanceProvider()
    return client._request_json(method, client.base_url + path, **data.get("arguments", {}))


def generic(db, tenant, data):
    from lifereel_api.providers.base import ProviderRequest
    from lifereel_api.providers.generic_media import GenericAsyncMediaProvider

    settings = get_settings()
    provider = GenericAsyncMediaProvider(
        data["name"],
        data["kind"],
        settings.media_provider_base_url or "",
        settings.media_provider_api_key or "",
    )
    action = data["action"]
    if action == "submit":
        return asdict(provider.submit(ProviderRequest(**data["request"]), data["idempotency_key"]))
    job_id = data["job_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", job_id):
        raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)
    if action == "status":
        return asdict(provider.get_status(job_id))
    if action == "cancel":
        return asdict(provider.cancel(job_id))
    if action == "outputs":
        return provider.fetch_outputs(job_id)
    raise ApiError(422, ErrorCode.REQUEST_VALIDATION_FAILED)


OPERATIONS = {
    "llm.chat": (CALLERS, chat),
    "model.audio": ({"media", "worker-media"}, audio),
    "model.image": ({"media", "worker-media"}, image_edit),
    "model.video-request": ({"media", "worker-media"}, video_request),
    "model.generic": ({"media", "worker-media"}, generic),
}

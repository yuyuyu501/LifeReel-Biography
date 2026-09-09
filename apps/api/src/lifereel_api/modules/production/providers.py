from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from lifereel_api.core.config import get_settings
from lifereel_api.providers.base import ProviderRequest
from lifereel_api.providers.generic_media import GenericAsyncMediaProvider


@dataclass
class ProviderOutput:
    content: bytes
    mime_type: str
    extension: str
    parameters: dict


class VideoProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        task_id: str | None = None,
        provider_status: str | None = None,
        provider_error_code: str | None = None,
    ) -> None:
        self.code = code
        self.task_id = task_id
        self.provider_status = provider_status
        self.provider_error_code = provider_error_code
        super().__init__(code)


class MockVideoProvider:
    name = "mock"

    def render(self, title: str, scenes: list[dict]) -> ProviderOutput:
        manifest = {
            "format": "lifereel.mock-video.v1",
            "title": title,
            "duration_seconds": sum(scene["duration_seconds"] for scene in scenes),
            "scenes": scenes,
            "notice": "Replace this manifest with a real provider-rendered MP4.",
        }
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            duration = max(3, min(90, manifest["duration_seconds"]))
            with tempfile.TemporaryDirectory(prefix="lifereel-render-") as temp_dir:
                output_path = Path(temp_dir) / "preview.mp4"
                command = [
                    ffmpeg,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=#315b57:s=720x1280:r=25",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=48000:cl=stereo",
                    "-t",
                    str(duration),
                    "-vf",
                    f"fade=t=in:st=0:d=0.8,fade=t=out:st={max(0, duration - 0.8)}:d=0.8",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "25",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "96k",
                    "-movflags",
                    "+faststart",
                    "-shortest",
                    str(output_path),
                ]
                subprocess.run(command, check=True, capture_output=True)
                content = output_path.read_bytes()
            return ProviderOutput(
                content=content,
                mime_type="video/mp4",
                extension="mp4",
                parameters={
                    "model": "local-ffmpeg-mock",
                    "duration_seconds": duration,
                    "manifest": manifest,
                    "sha256": hashlib.sha256(content).hexdigest(),
                },
            )
        content = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        return ProviderOutput(
            content=content,
            mime_type="application/json",
            extension="json",
            parameters={
                "model": "deterministic-mock",
                "sha256": hashlib.sha256(content).hexdigest(),
            },
        )


class GenericVideoProvider:
    def __init__(self, name: str) -> None:
        settings = get_settings()
        if not settings.media_provider_base_url or not settings.media_provider_api_key:
            raise ValueError("VIDEO_PROVIDER_CONFIGURATION_INCOMPLETE")
        self.adapter = GenericAsyncMediaProvider(
            name,
            "video",
            settings.media_provider_base_url,
            settings.media_provider_api_key,
        )
        self.poll_interval = settings.media_provider_poll_seconds
        self.timeout = settings.media_provider_timeout_seconds

    def render(self, title: str, scenes: list[dict]) -> ProviderOutput:
        request = ProviderRequest(
            kind="video",
            inputs={"title": title, "scenes": scenes},
            options={
                "aspect_ratio": "9:16",
                "duration_seconds": sum(s["duration_seconds"] for s in scenes),
            },
        )
        idempotency_key = hashlib.sha256(
            json.dumps(
                {"title": title, "scenes": scenes},
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        submission = self.adapter.submit(request, idempotency_key)
        deadline = time.monotonic() + self.timeout
        terminal_statuses = {
            "completed",
            "succeeded",
            "success",
            "failed",
            "cancelled",
            "canceled",
        }
        while submission.status.lower() not in terminal_statuses:
            if time.monotonic() >= deadline:
                try:
                    self.adapter.cancel(submission.provider_job_id)
                finally:
                    raise TimeoutError("VIDEO_PROVIDER_TIMEOUT")
            time.sleep(self.poll_interval)
            submission = self.adapter.get_status(submission.provider_job_id)
        if submission.status.lower() not in {"completed", "succeeded", "success"}:
            raise RuntimeError("VIDEO_PROVIDER_FAILED")
        outputs = self.adapter.fetch_outputs(submission.provider_job_id)
        if not outputs:
            raise RuntimeError("VIDEO_PROVIDER_OUTPUT_MISSING")
        content, mime_type, extension = self._read_output(outputs[0])
        return ProviderOutput(
            content=content,
            mime_type=mime_type,
            extension=extension,
            parameters={
                "model": self.adapter.name,
                "provider_job_id": submission.provider_job_id,
                "provider_status": submission.status,
                "output": {
                    key: value
                    for key, value in outputs[0].items()
                    if key not in {"base64", "content_base64"}
                },
            },
        )

    def _read_output(self, output: dict) -> tuple[bytes, str, str]:
        mime_type = str(output.get("mime_type") or output.get("content_type") or "video/mp4")
        encoded = output.get("content_base64") or output.get("base64")
        if encoded:
            content = base64.b64decode(encoded)
        else:
            url = output.get("url") or output.get("download_url") or output.get("content_url")
            if not url:
                raise RuntimeError("VIDEO_PROVIDER_OUTPUT_INVALID")
            provider_host = urlparse(self.adapter.base_url).netloc
            output_host = urlparse(str(url)).netloc
            headers = self.adapter.headers if provider_host == output_host else {}
            response = httpx.get(str(url), headers=headers, timeout=180, follow_redirects=True)
            response.raise_for_status()
            content = response.content
            mime_type = response.headers.get("content-type", mime_type).split(";", 1)[0]
        extension = str(output.get("extension") or "").lstrip(".")
        if not extension:
            extension = {
                "video/mp4": "mp4",
                "video/webm": "webm",
                "application/json": "json",
            }.get(mime_type, "bin")
        return content, mime_type, extension


class VolcengineSeedanceProvider:
    name = "volcengine-seedance"
    aliases = {name, "volcengine-seedance-1.5"}

    def __init__(self, client: httpx.Client | None = None, options: dict | None = None) -> None:
        settings = get_settings()
        if not settings.volcengine_api_key:
            raise VideoProviderError("VIDEO_PROVIDER_CONFIGURATION_INCOMPLETE")
        self.base_url = settings.volcengine_api_base_url.rstrip("/")
        self.model = settings.volcengine_video_model
        self.resolution = settings.volcengine_video_resolution
        self.ratio = settings.volcengine_video_ratio
        self.duration = settings.volcengine_video_duration
        self.generate_audio = settings.volcengine_video_generate_audio
        self.watermark = settings.volcengine_video_watermark
        for key in ("model", "resolution", "ratio", "duration", "generate_audio", "watermark"):
            if options and key in options:
                setattr(self, key, options[key])
        self.poll_interval = settings.volcengine_video_poll_seconds
        self.timeout = settings.volcengine_video_timeout_seconds
        self.headers = {
            "Authorization": f"Bearer {settings.volcengine_api_key}",
            "Content-Type": "application/json",
        }
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(60.0, connect=20.0),
            follow_redirects=True,
        )

    def render(self, title: str, scenes: list[dict]) -> ProviderOutput:
        prompt = self._build_prompt(title, scenes)
        request_body: dict[str, Any] = {
            "model": self.model,
            "content": [{"type": "text", "text": prompt}],
            "resolution": self.resolution,
            "ratio": self.ratio,
            "duration": self.duration,
            "seed": -1,
            "camera_fixed": False,
            "watermark": self.watermark,
        }
        if self.generate_audio:
            request_body["generate_audio"] = True
        task = self._request_json(
            "POST",
            f"{self.base_url}/contents/generations/tasks",
            json=request_body,
        )
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            raise VideoProviderError("VIDEO_PROVIDER_OUTPUT_INVALID")

        self._record_submission(task_id, self.duration)
        return self.fetch_segment(task_id, self.duration)

    def submit_segment(
        self,
        prompt: str,
        duration: int,
        reference_frame: bytes | None = None,
    ) -> str:
        if not 4 <= duration <= 15:
            raise VideoProviderError("VIDEO_DURATION_UNSUPPORTED")
        content: list[dict] = [{"type": "text", "text": prompt}]
        if reference_frame:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/jpeg;base64,"
                        + base64.b64encode(reference_frame).decode()
                    },
                    "role": "first_frame",
                }
            )
        result = self._request_json(
            "POST",
            f"{self.base_url}/contents/generations/tasks",
            json={
                "model": self.model,
                "content": content,
                "resolution": self.resolution,
                "ratio": self.ratio,
                "duration": duration,
                "generate_audio": self.generate_audio,
                "watermark": self.watermark,
                "seed": -1,
            },
        )
        if not result.get("id"):
            raise VideoProviderError("VIDEO_SUBMISSION_UNCERTAIN")
        self._record_submission(str(result["id"]), duration)
        return str(result["id"])

    def _record_submission(self, task_id: str, duration: int) -> None:
        from lifereel_api.modules.billing.usage import record

        record(
            self.model,
            "submitted",
            {
                "requested_duration_seconds": duration,
                "resolution": self.resolution,
                "generate_audio": self.generate_audio,
            },
            0,
            task_id,
        )

    def fetch_segment(self, task_id: str, duration: int) -> ProviderOutput:
        result = self._wait_for_result(task_id)
        from lifereel_api.modules.billing.usage import record

        record(
            self.model,
            "succeeded",
            {
                **(result.get("usage") or {}),
                "duration_seconds": result.get("duration", duration),
                "resolution": self.resolution,
                "generate_audio": self.generate_audio,
            },
            0,
            task_id,
        )
        video_url = self._video_url(result)
        if not video_url:
            raise VideoProviderError(
                "VIDEO_PROVIDER_OUTPUT_INVALID",
                task_id=task_id,
                provider_status=str(result.get("status") or ""),
            )
        content, mime_type = self._download_video(video_url, task_id)
        return ProviderOutput(
            content=content,
            mime_type=mime_type,
            extension="mp4",
            parameters={
                "model": self.model,
                "resolution": self.resolution,
                "ratio": self.ratio,
                "duration_seconds": result.get("duration", duration),
                "generate_audio": self.generate_audio,
                "watermark": self.watermark,
                "provider_job_id": task_id,
                "provider_status": str(result.get("status") or "succeeded"),
                "output_host": urlparse(video_url).netloc,
                "usage": result.get("usage") or {},
            },
        )

    def _wait_for_result(self, task_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        while True:
            result = self._request_json(
                "GET", f"{self.base_url}/contents/generations/tasks/{task_id}"
            )
            provider_status = str(result.get("status") or "").lower()
            if provider_status == "succeeded":
                return result
            if provider_status in {"failed", "expired", "cancelled", "canceled"}:
                error = result.get("error")
                provider_error_code = (
                    str(error.get("code"))
                    if isinstance(error, dict) and error.get("code")
                    else None
                )
                from lifereel_api.modules.billing.usage import record

                record(
                    self.model,
                    "failed",
                    result.get("usage") or {},
                    0,
                    task_id,
                    provider_error_code or "VIDEO_PROVIDER_FAILED",
                )
                raise VideoProviderError(
                    "VIDEO_PROVIDER_FAILED",
                    task_id=task_id,
                    provider_status=provider_status,
                    provider_error_code=provider_error_code,
                )
            if time.monotonic() >= deadline:
                raise VideoProviderError(
                    "VIDEO_PROVIDER_TIMEOUT",
                    task_id=task_id,
                    provider_status=provider_status or None,
                )
            time.sleep(self.poll_interval)

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.client.request(method, url, headers=self.headers, **kwargs)
        except httpx.HTTPError as exc:
            raise VideoProviderError("VIDEO_PROVIDER_REQUEST_FAILED") from exc
        if response.is_error:
            provider_error_code = self._provider_error_code(response)
            error_code = (
                "VIDEO_PROVIDER_CONFIGURATION_INCOMPLETE"
                if response.status_code in {401, 403}
                or provider_error_code == "InvalidEndpointOrModel.NotFound"
                else "VIDEO_PROVIDER_REQUEST_FAILED"
            )
            raise VideoProviderError(
                error_code, provider_error_code=provider_error_code, provider_status="rejected"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise VideoProviderError("VIDEO_PROVIDER_OUTPUT_INVALID") from exc
        if not isinstance(payload, dict):
            raise VideoProviderError("VIDEO_PROVIDER_OUTPUT_INVALID")
        return payload

    @staticmethod
    def _provider_error_code(response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict) or not error.get("code"):
            return None
        return str(error["code"])

    def _download_video(self, video_url: str, task_id: str) -> tuple[bytes, str]:
        try:
            response = self.client.get(video_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise VideoProviderError("VIDEO_PROVIDER_REQUEST_FAILED", task_id=task_id) from exc
        content = response.content
        if not content:
            raise VideoProviderError("VIDEO_PROVIDER_OUTPUT_INVALID", task_id=task_id)
        mime_type = response.headers.get("content-type", "video/mp4").split(";", 1)[0]
        if mime_type not in {"video/mp4", "application/octet-stream"}:
            raise VideoProviderError("VIDEO_PROVIDER_OUTPUT_INVALID", task_id=task_id)
        return content, "video/mp4"

    @staticmethod
    def _video_url(result: dict[str, Any]) -> str | None:
        content = result.get("content")
        if isinstance(content, dict):
            value = content.get("video_url")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _build_prompt(title: str, scenes: list[dict]) -> str:
        sections = [
            f"家庭传记短片《{title}》。纪实电影质感，真实自然，画面连贯。",
            "根据以下剧本内容生成画面；不添加字幕、标题、片尾文字，不虚构具体身份信息。",
        ]
        for index, scene in enumerate(scenes, start=1):
            heading = str(scene.get("heading") or f"第{index}章").strip()
            visual = str(scene.get("visual_prompt") or "").strip()
            narration = str(scene.get("narration") or "").strip()
            detail = "；".join(part for part in (visual, narration) if part)
            if detail:
                sections.append(f"{heading}：{detail}")
        return "\n".join(sections)[:2000]


def get_video_provider(name: str):
    if name == "mock":
        return MockVideoProvider()
    if name in VolcengineSeedanceProvider.aliases:
        return VolcengineSeedanceProvider()
    settings = get_settings()
    accepted_names = {
        settings.video_provider,
        settings.media_provider_name,
        f"{settings.media_provider_name}-video",
    }
    if name in accepted_names and name != "mock":
        return GenericVideoProvider(name)
    raise ValueError("VIDEO_PROVIDER_INVALID")

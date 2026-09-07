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


def get_video_provider(name: str):
    if name == "mock":
        return MockVideoProvider()
    settings = get_settings()
    accepted_names = {
        settings.video_provider,
        settings.media_provider_name,
        f"{settings.media_provider_name}-video",
    }
    if name in accepted_names and name != "mock":
        return GenericVideoProvider(name)
    raise ValueError("VIDEO_PROVIDER_INVALID")

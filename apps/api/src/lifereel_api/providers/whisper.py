from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

from lifereel_api.core.capacity import limited
from lifereel_api.core.config import get_settings
from lifereel_api.providers.base import ProviderCapabilities


@lru_cache(maxsize=4)
def _load_model(model_name: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device=device, compute_type=compute_type,
                        cpu_threads=get_settings().whisper_cpu_threads, num_workers=1)


class FasterWhisperClient:
    def __init__(
        self,
        model_name: str,
        device: str = "cpu",
        compute_type: str = "int8",
        *,
        hotwords: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        # Request-local hints must never become state on the cached model.
        self.hotwords = (hotwords or "").strip() or None

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="faster-whisper",
            kinds=("asr",),
            configured=bool(self.model_name),
        )

    @limited("asr")
    def transcribe(self, filename: str, content: bytes | Path, mime_type: str) -> str:
        suffix = Path(filename).suffix.lower()[:12] or ".audio"
        with tempfile.TemporaryDirectory(prefix="lifereel-whisper-") as temp_dir:
            source = content if isinstance(content, Path) else Path(temp_dir) / f"source{suffix}"
            if isinstance(content, bytes):
                source.write_bytes(content)
            model = _load_model(self.model_name, self.device, self.compute_type)
            hints = {}
            if self.hotwords:
                hints["hotwords"] = self.hotwords
            segments, _ = model.transcribe(
                str(source),
                language="zh",
                vad_filter=True,
                beam_size=5,
                **hints,
            )
            return "".join(segment.text for segment in segments).strip()

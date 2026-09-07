from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

from lifereel_api.providers.base import ProviderCapabilities


@lru_cache(maxsize=4)
def _load_model(model_name: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device=device, compute_type=compute_type)


class FasterWhisperClient:
    def __init__(self, model_name: str, device: str = "cpu", compute_type: str = "int8") -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="faster-whisper",
            kinds=("asr",),
            configured=bool(self.model_name),
        )

    def transcribe(self, filename: str, content: bytes, mime_type: str) -> str:
        suffix = Path(filename).suffix.lower()[:12] or ".audio"
        with tempfile.TemporaryDirectory(prefix="lifereel-whisper-") as temp_dir:
            source = Path(temp_dir) / f"source{suffix}"
            source.write_bytes(content)
            model = _load_model(self.model_name, self.device, self.compute_type)
            segments, _ = model.transcribe(
                str(source),
                language="zh",
                vad_filter=True,
                beam_size=5,
            )
            return "".join(segment.text for segment in segments).strip()

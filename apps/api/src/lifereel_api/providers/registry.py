from __future__ import annotations

from lifereel_api.core.config import get_settings
from lifereel_api.providers.base import ProviderCapabilities
from lifereel_api.providers.generic_media import GenericAsyncMediaProvider
from lifereel_api.providers.mock import MockProvider
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient
from lifereel_api.providers.whisper import FasterWhisperClient


def provider_capabilities() -> list[ProviderCapabilities]:
    settings = get_settings()
    capabilities = [
        MockProvider("llm").capabilities(),
        MockProvider("asr").capabilities(),
        MockProvider("image").capabilities(),
        MockProvider("video").capabilities(),
        MockProvider("voice").capabilities(),
    ]
    if settings.llm_provider == "openai-compatible" or settings.asr_provider == "openai-compatible":
        capabilities.append(
            OpenAICompatibleClient(
                settings.openai_compatible_base_url or "",
                settings.openai_compatible_api_key or "",
                settings.model_for("interview") or settings.model_for("asr"),
            ).capabilities()
        )
    if settings.asr_provider == "faster-whisper":
        capabilities.append(
            FasterWhisperClient(
                settings.asr_runtime_model,
                settings.whisper_device,
                settings.whisper_compute_type,
            ).capabilities()
        )
    if settings.media_provider_base_url or settings.media_provider_api_key:
        for kind in ("image", "video", "voice"):
            capabilities.append(
                GenericAsyncMediaProvider(
                    f"{settings.media_provider_name}-{kind}",
                    kind,
                    settings.media_provider_base_url or "",
                    settings.media_provider_api_key or "",
                ).capabilities()
            )
    return capabilities

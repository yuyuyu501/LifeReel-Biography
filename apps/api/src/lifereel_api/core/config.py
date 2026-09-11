from __future__ import annotations

from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "LifeReel Biography API"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    database_url: str = "sqlite:///./lifereel-dev.db"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_region_name: str | None = None
    s3_addressing_style: str = "auto"
    oss_direct_upload_enabled: bool = False
    s3_access_key: str = "lifereel"
    s3_secret_key: str = "change-me-in-production"
    s3_bucket: str = "lifereel-private"
    s3_server_side_encryption: str | None = None
    storage_backend: str = "local"
    local_storage_path: str = "../../data/private"
    default_tenant_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    auto_create_schema: bool = True
    log_level: str = "INFO"
    api_access_key: str | None = None
    auth_token_secret: str | None = None
    auth_token_minutes: int = 720
    auth_cookie_secure: bool | None = None
    bootstrap_owner_email: str | None = None
    bootstrap_owner_password: str | None = None
    bootstrap_owner_name: str = "家庭管理员"
    registration_enabled: bool = False
    billing_price_version: str = "standard-2026-09-luna20"
    billing_welcome_bonus_cents: int = Field(default=2000, ge=0, le=100000)
    billing_video_cents_per_second: int = Field(default=80, ge=0, le=10000)
    billing_video_mode: Literal["per_second", "tokens"] = "tokens"
    billing_video_reserve_cents: int = Field(default=2400, ge=1, le=100000)
    billing_script_chapter_cents: int = Field(default=40, ge=0, le=10000)
    billing_text_mode: Literal["per_successful_chapter_update", "tokens"] = (
        "per_successful_chapter_update"
    )
    manual_wechat_enabled: bool = False
    manual_wechat_qr_path: str = "/data/payments/wechat-qr.png"
    max_evidence_image_bytes: int = 20 * 1024 * 1024
    max_evidence_document_bytes: int = 50 * 1024 * 1024
    max_evidence_audio_bytes: int = 500 * 1024 * 1024
    max_evidence_video_bytes: int = 2 * 1024 * 1024 * 1024
    execute_mock_jobs_inline: bool = True
    worker_queue: str = "lifereel:jobs"

    llm_provider: str = "mock"
    asr_provider: str = "mock"
    video_provider: str = "mock"
    image_provider: str = "mock"
    voice_provider: str = "mock"
    openai_compatible_base_url: str | None = None
    openai_compatible_api_key: str | None = None
    openai_compatible_model: str | None = None
    interview_llm_model: str | None = None
    memory_llm_model: str | None = None
    script_llm_model: str | None = None
    vision_llm_model: str | None = None
    asr_model: str | None = None
    whisper_model_path: str | None = None
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    media_provider_name: str = "generic-media"
    media_provider_base_url: str | None = None
    media_provider_api_key: str | None = None
    media_provider_poll_seconds: float = 2.0
    media_provider_timeout_seconds: int = 900
    volcengine_api_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    volcengine_api_key: str | None = None
    volcengine_video_model: str = "doubao-seedance-2-0-mini-260615"
    volcengine_video_resolution: str = "720p"
    volcengine_video_ratio: str = "16:9"
    volcengine_video_duration: int = 5
    volcengine_video_generate_audio: bool = True
    volcengine_video_watermark: bool = True
    volcengine_video_poll_seconds: float = 10.0
    volcengine_video_timeout_seconds: int = 900

    @field_validator("api_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_development(self) -> bool:
        return self.app_env in {"development", "test"}

    @property
    def cookie_secure(self) -> bool:
        if self.auth_cookie_secure is not None:
            return self.auth_cookie_secure
        return not self.is_development

    def model_for(self, capability: str) -> str:
        configured = {
            "interview": self.interview_llm_model,
            "memory": self.memory_llm_model,
            "script": self.script_llm_model,
            "vision": self.vision_llm_model,
            "asr": self.asr_model,
        }.get(capability)
        return configured or self.openai_compatible_model or ""

    @property
    def asr_runtime_model(self) -> str:
        if self.asr_provider == "faster-whisper" and self.whisper_model_path:
            return self.whisper_model_path
        return self.model_for("asr")


@lru_cache
def get_settings() -> Settings:
    return Settings()

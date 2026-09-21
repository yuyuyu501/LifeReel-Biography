"""Processing budgets are separate from upload limits; originals remain downloadable."""

from pydantic import BaseModel, Field

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode

MEMORY_INPUT_MAX_CHARS = 20_000


def require_memory_input(text: str, *, source_asset_id: str | None = None) -> None:
    require_budget(
        len(text), MEMORY_INPUT_MAX_CHARS, stage="memory_input",
        code=ErrorCode.MEMORY_INPUT_TOO_LARGE, source_asset_id=source_asset_id,
    )


class ProcessingLimits(BaseModel):
    """Typed view for processing code/tests; only central Settings reads the environment."""

    document_extract_max_chars: int = Field(default=16_000, gt=0, le=200_000)
    document_extract_max_pages: int = Field(default=200, gt=0, le=1000)
    script_input_max_chars: int = Field(default=48_000, gt=0, le=200_000)


def get_processing_limits() -> ProcessingLimits:
    # get_settings is cached; never read .env per extraction or script generation.
    settings = get_settings()
    return ProcessingLimits(**{
        name: getattr(settings, name)
        for name in ProcessingLimits.model_fields
    })


def require_budget(
    actual: int, limit: int, *, stage: str, code: ErrorCode,
    unit: str = "chars", source_asset_id: str | None = None,
) -> None:
    if actual <= limit:
        return
    context = {
        "reason": "processing_budget_exceeded", "stage": stage,
        f"limit_{unit}": limit, "coverage": "none",
        "action": "split_source_and_retry",
    }
    if source_asset_id is not None:
        context["source_asset_id"] = source_asset_id
        context["original_preserved"] = True
    raise ApiError(413, code, context)

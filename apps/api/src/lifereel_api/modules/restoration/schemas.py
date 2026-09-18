from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PhotoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    original_filename: str
    mime_type: str
    byte_size: int
    created_at: datetime


class StartRequest(BaseModel):
    photo_id: UUID
    colorize: bool = False


class SaveRequest(BaseModel):
    subject_id: UUID


class RestorationRead(BaseModel):
    id: UUID
    photo: PhotoRead
    status: str
    colorize: bool
    error_code: str | None
    can_retry: bool
    created_at: datetime


class HistoryRead(BaseModel):
    items: list[RestorationRead]
    total: int
    page: int
    page_size: int

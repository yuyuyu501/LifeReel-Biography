from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PersonCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    preferred_name: str | None = Field(default=None, max_length=120)
    birth_year: int | None = Field(default=None, ge=1850, le=2100)
    birthplace: str | None = Field(default=None, max_length=240)
    relation_to_owner: str | None = Field(default=None, max_length=80)
    is_subject: bool = True
    biography_note: str | None = None
    is_minor: bool = False
    guardian_name: str | None = Field(default=None, max_length=120)


class PersonUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    preferred_name: str | None = Field(default=None, max_length=120)
    birth_year: int | None = Field(default=None, ge=1850, le=2100)
    birthplace: str | None = Field(default=None, max_length=240)
    relation_to_owner: str | None = Field(default=None, max_length=80)
    is_subject: bool | None = None
    biography_note: str | None = None
    is_minor: bool | None = None
    guardian_name: str | None = Field(default=None, max_length=120)

    @field_validator("display_name", "is_subject", "is_minor")
    @classmethod
    def reject_null_for_required_fields(cls, value):
        if value is None:
            raise ValueError("field cannot be null")
        return value


class PersonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    display_name: str
    preferred_name: str | None
    birth_year: int | None
    birthplace: str | None
    relation_to_owner: str | None
    is_subject: bool
    biography_note: str | None
    is_minor: bool
    guardian_name: str | None
    created_at: datetime
    updated_at: datetime

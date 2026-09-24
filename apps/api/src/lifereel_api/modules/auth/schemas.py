from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Password = Annotated[str, Field(min_length=8, max_length=200)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^1[3-9]\d{9}$")]
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        max_length=255,
    ),
]


class LoginRequest(BaseModel):
    # Compatibility with existing clients: this field accepts email or phone.
    email: str = Field(min_length=3, max_length=255)
    password: Password

    @field_validator("email")
    @classmethod
    def normalize_login(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"1[3-9]\d{9}|[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("INVALID_LOGIN")
        return value


class AuthUserRead(BaseModel):
    id: UUID
    email: str | None = None
    phone: str | None = None
    display_name: str
    tenant_id: UUID
    role: str
    is_admin: bool = False


class SmsRequest(BaseModel):
    phone: Phone
    purpose: Literal["register", "reset_password", "bind_phone", "delete_account"]


class SmsVerification(BaseModel):
    phone: Phone
    challenge_id: UUID
    code: str = Field(pattern=r"^\d{6}$")


class RegisterRequest(SmsVerification):
    display_name: Name
    password: Password


class PasswordReset(SmsVerification):
    password: Password


class ProfileUpdate(BaseModel):
    display_name: Name


class PasswordChange(BaseModel):
    current_password: Password
    password: Password


class PhoneChange(SmsVerification):
    current_password: Password


class AccountDelete(BaseModel):
    current_password: Password
    challenge_id: UUID | None = None
    code: str | None = Field(default=None, pattern=r"^\d{6}$")


class AdminCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Email
    display_name: Name
    password: Password


class AdminUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: Name | None = None
    email: Email | None = None
    is_active: bool | None = None
    password: Password | None = None


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str | None
    phone: str | None
    display_name: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    deleted_at: datetime | None


class AccountPage(BaseModel):
    items: list[AccountRead]
    total: int
    page: int
    page_size: int


class LoginResponse(BaseModel):
    expires_in: int
    user: AuthUserRead


class MiniProgramLoginRequest(BaseModel):
    platform: Literal["wechat", "douyin"]
    code: str = Field(min_length=1, max_length=512)
    display_name: Name | None = None


class MiniProgramRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=256)


class PlatformIdentityRead(BaseModel):
    id: UUID
    platform: Literal["wechat", "douyin"]
    app_id: str
    created_at: datetime


class MiniProgramAuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: AuthUserRead
    identity: PlatformIdentityRead


class MiniProgramIdentityResponse(BaseModel):
    identity: PlatformIdentityRead
    auth: MiniProgramAuthResponse

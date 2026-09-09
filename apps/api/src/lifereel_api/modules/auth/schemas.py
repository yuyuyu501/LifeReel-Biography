from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    password: str = Field(min_length=8, max_length=200)


class AuthUserRead(BaseModel):
    id: UUID
    email: str
    display_name: str
    tenant_id: UUID
    role: str


class RegisterRequest(LoginRequest):
    display_name: str = Field(min_length=1, max_length=80)


class LoginResponse(BaseModel):
    expires_in: int
    user: AuthUserRead

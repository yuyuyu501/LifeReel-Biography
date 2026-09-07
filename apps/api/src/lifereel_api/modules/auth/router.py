from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import get_db
from lifereel_api.modules.auth import service
from lifereel_api.modules.auth.dependencies import AuthContext, auth_context
from lifereel_api.modules.auth.schemas import AuthUserRead, LoginRequest, LoginResponse

router = APIRouter(prefix="/auth", tags=["auth"])
Db = Annotated[Session, Depends(get_db)]
Context = Annotated[AuthContext, Depends(auth_context)]


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Db, response: Response) -> LoginResponse:
    result, session_token = service.login(db, payload.email, payload.password)
    settings = get_settings()
    response.set_cookie(
        "lifereel_session",
        session_token,
        max_age=result.expires_in,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return result


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        "lifereel_session",
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.get("/me", response_model=AuthUserRead)
def me(context: Context, db: Db) -> AuthUserRead:
    if context.user_id is None:
        return AuthUserRead(
            id=context.tenant_id,
            email="development@local",
            display_name="开发用户",
            tenant_id=context.tenant_id,
            role=context.role,
        )
    return service.user_context(db, context.user_id, context.tenant_id)

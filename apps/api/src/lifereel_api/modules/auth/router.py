from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import get_db
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.auth import mini_program, service, sms
from lifereel_api.modules.auth.dependencies import AuthContext, auth_context
from lifereel_api.modules.auth.schemas import (
    AccountDelete,
    AccountPage,
    AccountRead,
    AdminCreate,
    AdminUpdate,
    AuthUserRead,
    LoginRequest,
    LoginResponse,
    MiniProgramAuthResponse,
    MiniProgramIdentityResponse,
    MiniProgramLoginRequest,
    MiniProgramRefreshRequest,
    PasswordChange,
    PasswordReset,
    PhoneChange,
    PlatformIdentityRead,
    ProfileUpdate,
    RegisterRequest,
    SmsRequest,
)
from lifereel_api.modules.auth.security import decode_token, hash_password
from lifereel_api.modules.auth.throttle import client_address, limit

router = APIRouter(prefix="/auth", tags=["auth"])
Db = Annotated[Session, Depends(get_db)]
Context = Annotated[AuthContext, Depends(auth_context)]


@router.get("/registration")
def registration_settings() -> dict:
    return {
        "enabled": get_settings().registration_enabled,
        "sms_enabled": sms.configured(),
        "password_reset_enabled": sms.configured("reset_password"),
        "phone_verification_enabled": sms.configured("bind_phone"),
    }


@router.post("/register", response_model=AuthUserRead, status_code=201)
def register(payload: RegisterRequest, db: Db, request: Request):
    limit("register-ip", client_address(request), 20, 600)
    return service.register(db, payload)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Db, response: Response, request: Request) -> LoginResponse:
    limit("login-ip", client_address(request), 100, 600)
    limit("login-account", payload.email, 15, 600)
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


def _mini_auth_response(db: Db, user, identity, pair) -> MiniProgramAuthResponse:
    return MiniProgramAuthResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
        user=service.user_context(db, user.id, identity.tenant_id),
        identity=PlatformIdentityRead(
            id=identity.id,
            platform=identity.platform,
            app_id=identity.app_id,
            created_at=identity.created_at,
        ),
    )


@router.post("/mini-program/login", response_model=MiniProgramAuthResponse)
async def mini_program_login(payload: MiniProgramLoginRequest, db: Db):
    code_identity = await mini_program.exchange_code(payload.platform, payload.code)
    user, identity, pair, _created = mini_program.login_or_register(
        db, code_identity, display_name=payload.display_name
    )
    return _mini_auth_response(db, user, identity, pair)


@router.post("/mini-program/refresh", response_model=MiniProgramAuthResponse)
def mini_program_refresh(payload: MiniProgramRefreshRequest, db: Db):
    user, identity, pair = mini_program.refresh(db, payload.refresh_token)
    return _mini_auth_response(db, user, identity, pair)


@router.post("/mini-program/link", response_model=MiniProgramIdentityResponse)
async def mini_program_link(payload: MiniProgramLoginRequest, db: Db, context: Context):
    user_id = authenticated_id(context)
    code_identity = await mini_program.exchange_code(payload.platform, payload.code)
    identity, pair = mini_program.link(db, user_id, context.tenant_id, code_identity)
    user = service.require_user(db, user_id, lock=False)
    return MiniProgramIdentityResponse(
        identity=PlatformIdentityRead(
            id=identity.id,
            platform=identity.platform,
            app_id=identity.app_id,
            created_at=identity.created_at,
        ),
        auth=_mini_auth_response(db, user, identity, pair),
    )


@router.post("/logout", status_code=204)
def logout(response: Response, request: Request, db: Db) -> None:
    token = request.cookies.get("lifereel_session")
    if token:
        try:
            payload = decode_token(token)
            user = service.require_user(db, UUID(payload["sub"]))
            if payload.get("version", 0) == user.session_version:
                user.session_version += 1
                db.commit()
        except ApiError:
            db.rollback()
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


def authenticated_id(context: AuthContext) -> UUID:
    if context.user_id is None:
        raise ApiError(401, ErrorCode.AUTH_REQUIRED)
    return context.user_id


def admin(context: Context, db: Db) -> UUID:
    user_id = authenticated_id(context)
    user = service.require_user(db, user_id, lock=False)
    if not user.is_admin or not user.is_active:
        raise ApiError(403, ErrorCode.AUTH_ADMIN_REQUIRED)
    return user_id


Admin = Annotated[UUID, Depends(admin)]


@router.post("/sms")
def send_sms(payload: SmsRequest, db: Db, request: Request) -> dict:
    if payload.purpose == "register" and not get_settings().registration_enabled:
        raise ApiError(403, ErrorCode.REGISTRATION_DISABLED)
    if payload.purpose in {"bind_phone", "delete_account"}:
        token = request.cookies.get("lifereel_session")
        if not token:
            raise ApiError(401, ErrorCode.AUTH_REQUIRED)
        claims = decode_token(token)
        user = service.require_user(db, UUID(claims["sub"]), lock=False)
        if not user.is_active or claims.get("version", 0) != user.session_version:
            raise ApiError(401, ErrorCode.AUTH_SESSION_INACTIVE)
        if payload.purpose == "delete_account" and payload.phone != user.phone:
            raise ApiError(400, ErrorCode.SMS_CODE_INVALID)
    return sms.issue(db, payload.phone, payload.purpose, client_address(request))


@router.post("/password/reset", status_code=204)
def reset_password(payload: PasswordReset, db: Db, request: Request) -> None:
    limit("password-reset-ip", client_address(request), 20, 600)
    service.reset_password(db, payload)


@router.patch("/me", response_model=AuthUserRead)
def update_profile(payload: ProfileUpdate, db: Db, context: Context):
    user = service.require_user(db, authenticated_id(context))
    user.display_name = payload.display_name
    service.audit(db, user.id, user.id, "profile.updated", fields=["display_name"])
    db.commit()
    return service.user_context(db, user.id, context.tenant_id)


@router.post("/password", status_code=204)
def change_password(payload: PasswordChange, db: Db, context: Context) -> None:
    user_id = authenticated_id(context)
    limit("password-change", str(user_id), 10, 600)
    user = service.require_user(db, user_id)
    service.require_password(user, payload.current_password)
    user.password_hash = hash_password(payload.password)
    user.session_version += 1
    service.audit(db, user.id, user.id, "password.changed")
    db.commit()


@router.put("/phone", status_code=204)
def change_phone(payload: PhoneChange, db: Db, context: Context) -> None:
    user_id = authenticated_id(context)
    limit("phone-change", str(user_id), 10, 600)
    sms.consume(db, payload, "bind_phone")
    user = service.require_user(db, user_id)
    service.require_password(user, payload.current_password)
    service.claim_phone(db, user, payload.phone)
    user.phone = payload.phone
    user.session_version += 1
    service.audit(db, user.id, user.id, "phone.changed")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, ErrorCode.AUTH_ACCOUNT_UNAVAILABLE) from exc


@router.delete("/me", status_code=204)
def close_account(payload: AccountDelete, db: Db, context: Context) -> None:
    user_id = authenticated_id(context)
    limit("account-close", str(user_id), 10, 600)
    service.delete_account(db, user_id, user_id, payload)


@router.get("/accounts", response_model=AccountPage)
def accounts(
    db: Db,
    actor: Admin,
    q: str = Query(default="", max_length=100),
    state: Literal["all", "active", "inactive"] = "all",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return service.list_accounts(db, q.strip(), state, page, page_size)


@router.post("/accounts", response_model=AccountRead, status_code=201)
def create_account(payload: AdminCreate, db: Db, actor: Admin):
    limit("admin-create", str(actor), 30, 600)
    return service.admin_create(db, actor, payload)


@router.get("/accounts/{user_id}", response_model=AccountRead)
def get_account(user_id: UUID, db: Db, actor: Admin):
    return service.require_user(db, user_id, lock=False)


@router.patch("/accounts/{user_id}", response_model=AccountRead)
def update_account(user_id: UUID, payload: AdminUpdate, db: Db, actor: Admin):
    return service.admin_update(db, actor, user_id, payload)


@router.delete("/accounts/{user_id}", status_code=204)
def remove_account(user_id: UUID, db: Db, actor: Admin):
    service.delete_account(db, actor, user_id)

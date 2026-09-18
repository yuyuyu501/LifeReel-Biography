from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Header, status
from starlette.requests import HTTPConnection

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.auth.dependencies import PUBLIC_AUTH_PATHS


def require_api_access(
    request: HTTPConnection,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    settings = get_settings()
    request.state.internal_access = False
    if settings.is_development or request.url.path.startswith("/v1/public/"):
        return
    if request.url.path in PUBLIC_AUTH_PATHS:
        request.state.internal_access = bool(
            settings.api_access_key
            and x_api_key
            and secrets.compare_digest(x_api_key, settings.api_access_key)
        )
        return
    if not settings.api_access_key:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code=ErrorCode.API_KEY_NOT_CONFIGURED,
        )
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_access_key):
        raise ApiError(status.HTTP_401_UNAUTHORIZED, ErrorCode.API_KEY_INVALID)
    request.state.internal_access = True

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header

from lifereel_api.modules.auth.dependencies import AuthContext, auth_context


def get_tenant_id(context: Annotated[AuthContext, Depends(auth_context)]) -> UUID:
    return context.tenant_id


TenantId = Annotated[UUID, Header(alias="X-Tenant-ID")]

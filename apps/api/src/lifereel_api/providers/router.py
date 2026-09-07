from fastapi import APIRouter

from lifereel_api.providers.registry import provider_capabilities

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("")
def providers() -> list[dict]:
    return [
        {
            "name": item.name,
            "kinds": item.kinds,
            "configured": item.configured,
            "supports_webhooks": item.supports_webhooks,
            "supports_cancel": item.supports_cancel,
        }
        for item in provider_capabilities()
    ]

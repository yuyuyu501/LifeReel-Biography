from fastapi import APIRouter, Depends

from lifereel_api.core.security import require_api_access
from lifereel_api.modules.auth.dependencies import enforce_write_role
from lifereel_api.modules.auth.router import router as auth_router
from lifereel_api.modules.billing.router import router as billing_router
from lifereel_api.modules.evidence.router import router as evidence_router
from lifereel_api.modules.governance.router import router as governance_router
from lifereel_api.modules.identity.router import router as identity_router
from lifereel_api.modules.interview.router import router as interview_router
from lifereel_api.modules.jobs.router import router as jobs_router
from lifereel_api.modules.memory.router import router as memory_router
from lifereel_api.modules.orchestration.router import router as orchestration_router
from lifereel_api.modules.production.router import router as production_router
from lifereel_api.modules.publication.router import router as publication_router
from lifereel_api.modules.restoration.router import router as restoration_router
from lifereel_api.modules.script.router import router as script_router
from lifereel_api.providers.router import router as providers_router

api_router = APIRouter(
    prefix="/v1",
    dependencies=[Depends(require_api_access), Depends(enforce_write_role)],
)
api_router.include_router(auth_router)
api_router.include_router(billing_router)
api_router.include_router(evidence_router)
api_router.include_router(restoration_router)
api_router.include_router(identity_router)
api_router.include_router(interview_router)
api_router.include_router(jobs_router)
api_router.include_router(memory_router)
api_router.include_router(orchestration_router)
api_router.include_router(script_router)
api_router.include_router(governance_router)
api_router.include_router(production_router)
api_router.include_router(publication_router)
api_router.include_router(providers_router)

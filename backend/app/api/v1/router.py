from fastapi import APIRouter

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.documents import router as documents_router
from app.api.v1.endpoints.vendors import router as vendors_router
from app.api.v1.endpoints.purchase_orders import router as po_router
from app.api.v1.endpoints.approvals import router as approvals_router
from app.api.v1.endpoints.exceptions import router as exceptions_router
from app.api.v1.endpoints.dashboard import router as dashboard_router
from app.api.v1.endpoints.admin import router as admin_router
# Phase 5: new LangGraph-aware endpoints
from app.api.v1.endpoints.workflows import router as workflows_router
from app.api.v1.endpoints.prompts import router as prompts_router
from app.api.v1.endpoints.config_endpoint import router as config_router

api_router = APIRouter(prefix="/api/v1")

# Preserved — unchanged, fully backward compatible
api_router.include_router(auth_router)
api_router.include_router(documents_router)
api_router.include_router(vendors_router)
api_router.include_router(po_router)
api_router.include_router(approvals_router)
api_router.include_router(exceptions_router)
api_router.include_router(dashboard_router)
api_router.include_router(admin_router)

# Phase 5 additions — new prefix paths, no conflict with existing
api_router.include_router(workflows_router)
api_router.include_router(prompts_router)
api_router.include_router(config_router)

# Phase 8: Explainability — adds new paths under existing prefixes (no conflict)
from app.api.v1.endpoints.explain import (
    documents_explain_router,
    exceptions_explain_router,
    approvals_explain_router,
)
api_router.include_router(documents_explain_router)
api_router.include_router(exceptions_explain_router)
api_router.include_router(approvals_explain_router)

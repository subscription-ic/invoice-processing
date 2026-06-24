"""
Tenant middleware — extracts X-Tenant-ID from request headers.

Injects tenant_id into request.state so all new endpoints can read it.
Existing endpoints are unaffected — they never read request.state.tenant_id.

Default: "default" (keeps backward compatibility).
"""
from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class TenantMiddleware(BaseHTTPMiddleware):
    DEFAULT_TENANT = "default"

    def __init__(self, app: ASGIApp, default_tenant: str = "default") -> None:
        super().__init__(app)
        self.default_tenant = default_tenant

    async def dispatch(self, request: Request, call_next):
        tenant_id = request.headers.get("X-Tenant-ID", self.default_tenant).strip()
        if not tenant_id:
            tenant_id = self.default_tenant
        request.state.tenant_id = tenant_id
        response = await call_next(request)
        return response


def get_tenant_id(request: Request) -> str:
    """FastAPI dependency — returns tenant_id from request state."""
    return getattr(request.state, "tenant_id", "default")

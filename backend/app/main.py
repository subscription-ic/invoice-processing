from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.core.config import settings
from app.core.database import check_db_connection
from app.api.v1.router import api_router
from app.services.storage.local_storage import get_storage
from app.middleware.tenant_middleware import TenantMiddleware
from core.container import get_container

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    # Startup
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    # Ensure upload directories exist
    try:
        storage = get_storage()
        await storage.ensure_directories()
    except Exception as exc:
        logger.warning(f"Storage init warning (non-fatal): {exc}")

    # Database connectivity check
    db_ok = await check_db_connection()
    if not db_ok:
        logger.error("Database connection failed — some features will be unavailable")
    else:
        logger.info("Database connection OK")

    # Phase 4+: compile LangGraph graphs in background (non-fatal)
    async def _start_graph_registry():
        try:
            from app.core.graph_registry import GraphRegistry
            registry = GraphRegistry.get_instance()
            await asyncio.wait_for(registry.startup(), timeout=30.0)
            logger.info("GraphRegistry ready")
        except asyncio.TimeoutError:
            logger.warning("GraphRegistry startup timed out (non-fatal)")
        except Exception as exc:
            logger.warning(f"GraphRegistry startup warning (non-fatal): {exc}")

    asyncio.create_task(_start_graph_registry())

    logger.info("Application startup complete")
    yield

    # Shutdown
    logger.info("Shutting down AP Platform")
    try:
        await get_container().shutdown()
    except Exception:
        pass


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-powered Accounts Payable Automation Platform",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Phase 5: tenant identification from X-Tenant-ID header (non-breaking)
app.add_middleware(TenantMiddleware, default_tenant=settings.DEFAULT_TENANT_ID)

app.include_router(api_router)


@app.get("/health")
async def health():
    db_ok = await check_db_connection()
    return {
        "status": "healthy" if db_ok else "degraded",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "database": "connected" if db_ok else "disconnected",
    }
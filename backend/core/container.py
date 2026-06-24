"""
PlatformContainer — dependency injection container for the entire platform.

Provides a single source of lazily-initialised, singleton instances for:
  - Repositories (DocumentRepository, VendorRepository, …)
  - Providers (OCR, LLM, ERP, Storage)
  - Logger

Usage:
    container = PlatformContainer.get()
    doc_repo = container.document_repository
    llm = container.llm_provider

The container reads its configuration from PlatformConfig (YAML + env overrides).
It does NOT use third-party DI frameworks so there are no additional dependencies.

Thread/async safety: All attributes use double-checked initialisation guarded by
a threading.Lock. This is safe because all providers and repositories are
stateless (or hold only read-heavy shared state like DB connection pools).
"""

from __future__ import annotations

import threading
from typing import Optional

from contextlib import asynccontextmanager


class PlatformContainer:
    """
    Singleton DI container.

    Call PlatformContainer.get() anywhere in the application.
    Call PlatformContainer.reset() in tests to replace providers with mocks.
    """

    _instance: Optional["PlatformContainer"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._initialised = False
        self._init_lock = threading.Lock()

        # Lazy-initialised singletons
        self._document_repository = None
        self._vendor_repository = None
        self._po_repository = None
        self._grn_repository = None
        self._workflow_repository = None
        self._audit_repository = None

        self._ocr_provider = None
        self._llm_provider = None
        self._erp_provider = None
        self._storage_provider = None

        self._logger = None
        self._platform_config = None

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------

    @classmethod
    def get(cls) -> "PlatformContainer":
        """Return the shared container instance, creating it on first call."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Destroy the singleton (useful in tests to inject mocks)."""
        with cls._lock:
            cls._instance = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def platform_config(self):
        if self._platform_config is None:
            with self._init_lock:
                if self._platform_config is None:
                    from core.config.platform_config import get_platform_config
                    self._platform_config = get_platform_config()
        return self._platform_config

    # ------------------------------------------------------------------
    # Logger
    # ------------------------------------------------------------------

    @property
    def logger(self):
        if self._logger is None:
            with self._init_lock:
                if self._logger is None:
                    from core.logging.structured_logger import get_logger
                    from app.core.config import settings
                    self._logger = get_logger(
                        "platform.container",
                        environment=settings.ENVIRONMENT,
                    )
        return self._logger

    # ------------------------------------------------------------------
    # Repositories
    # ------------------------------------------------------------------

    @property
    def document_repository(self):
        if self._document_repository is None:
            with self._init_lock:
                if self._document_repository is None:
                    from core.repositories.document_repository import DocumentRepository
                    from app.core.database import AsyncSessionLocal
                    self._document_repository = DocumentRepository(session_factory=AsyncSessionLocal)
        return self._document_repository

    @property
    def vendor_repository(self):
        if self._vendor_repository is None:
            with self._init_lock:
                if self._vendor_repository is None:
                    from core.repositories.vendor_repository import VendorRepository
                    from app.core.database import AsyncSessionLocal
                    self._vendor_repository = VendorRepository(session_factory=AsyncSessionLocal)
        return self._vendor_repository

    @property
    def po_repository(self):
        if self._po_repository is None:
            with self._init_lock:
                if self._po_repository is None:
                    from core.repositories.vendor_repository import PurchaseOrderRepository
                    from app.core.database import AsyncSessionLocal
                    self._po_repository = PurchaseOrderRepository(session_factory=AsyncSessionLocal)
        return self._po_repository

    @property
    def grn_repository(self):
        if self._grn_repository is None:
            with self._init_lock:
                if self._grn_repository is None:
                    from core.repositories.vendor_repository import GRNRepository
                    from app.core.database import AsyncSessionLocal
                    self._grn_repository = GRNRepository(session_factory=AsyncSessionLocal)
        return self._grn_repository

    @property
    def workflow_repository(self):
        if self._workflow_repository is None:
            with self._init_lock:
                if self._workflow_repository is None:
                    from core.repositories.workflow_repository import WorkflowRepository
                    from app.core.database import AsyncSessionLocal
                    self._workflow_repository = WorkflowRepository(session_factory=AsyncSessionLocal)
        return self._workflow_repository

    @property
    def audit_repository(self):
        if self._audit_repository is None:
            with self._init_lock:
                if self._audit_repository is None:
                    from core.repositories.audit_repository import AuditRepository
                    from app.core.database import AsyncSessionLocal
                    self._audit_repository = AuditRepository(session_factory=AsyncSessionLocal)
        return self._audit_repository

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------

    @property
    def ocr_provider(self):
        if self._ocr_provider is None:
            with self._init_lock:
                if self._ocr_provider is None:
                    from core.providers.ocr_provider import TesseractOCRProvider
                    from app.core.config import settings
                    import pytesseract

                    if settings.TESSERACT_CMD:
                        pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD

                    ocr_cfg = self.platform_config.get_tenant_config().ocr
                    self._ocr_provider = TesseractOCRProvider(
                        dpi=ocr_cfg.dpi,
                        lang="eng",
                    )
        return self._ocr_provider

    @property
    def llm_provider(self):
        if self._llm_provider is None:
            with self._init_lock:
                if self._llm_provider is None:
                    from core.providers.llm_provider import OpenAILLMProvider
                    from app.core.config import settings
                    self._llm_provider = OpenAILLMProvider(
                        api_key=settings.OPENAI_API_KEY or None,
                        default_model=settings.OPENAI_MODEL,
                    )
        return self._llm_provider

    @property
    def erp_provider(self):
        if self._erp_provider is None:
            with self._init_lock:
                if self._erp_provider is None:
                    from core.providers.erp_provider import MockERPAdapter
                    erp_cfg = self.platform_config.get_tenant_config().erp
                    self._erp_provider = MockERPAdapter(
                        allow_mock_in_production=erp_cfg.allow_mock_in_production,
                    )
        return self._erp_provider

    @property
    def storage_provider(self):
        if self._storage_provider is None:
            with self._init_lock:
                if self._storage_provider is None:
                    from core.providers.storage_provider import LocalStorageAdapter
                    from app.core.config import settings
                    storage_cfg = self.platform_config.get_tenant_config().storage
                    self._storage_provider = LocalStorageAdapter(
                        base_dir=settings.UPLOAD_DIR,
                        allow_local_in_production=storage_cfg.allow_local_in_production,
                    )
        return self._storage_provider

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> dict:
        """Run health checks on all providers. Used by /health endpoint."""
        results = {}
        for name, provider in [
            ("ocr", self.ocr_provider),
            ("llm", self.llm_provider),
            ("erp", self.erp_provider),
            ("storage", self.storage_provider),
        ]:
            try:
                results[name] = await provider.health_check()
            except Exception as exc:
                results[name] = False
                self.logger.warning(
                    f"Health check failed for {name}: {exc}",
                    component="PlatformContainer",
                )
        return results

    # ------------------------------------------------------------------
    # Async context manager (for lifespan use)
    # ------------------------------------------------------------------

    async def startup(self) -> None:
        """Warm up providers that require async initialisation."""
        try:
            await self.storage_provider.ensure_directories()
            self.logger.info("PlatformContainer started", component="PlatformContainer")
        except Exception as exc:
            self.logger.error(
                f"Container startup error: {exc}", component="PlatformContainer"
            )
            raise

    async def shutdown(self) -> None:
        """Release any resources held by the container."""
        self.logger.info("PlatformContainer shutting down", component="PlatformContainer")


# Module-level convenience accessor
def get_container() -> PlatformContainer:
    return PlatformContainer.get()

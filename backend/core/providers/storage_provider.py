"""
StorageProvider — platform-level interface wrapping the existing app/services/storage layer.

Production guard: if allow_local_in_production is False and the environment is
production, LocalStorageAdapter will raise an exception.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import ClassVar, Optional

from core.base.provider import BaseProvider


class StorageProviderInterface(BaseProvider):
    """
    Abstract storage provider.

    Implementations: LocalStorageAdapter (active), AzureBlobStorageAdapter (Phase 9).
    """

    provider_type: ClassVar[str] = "storage"

    @abstractmethod
    async def save_file(self, content: bytes, destination_path: str) -> str:
        """Persist bytes at destination_path and return the canonical path/URL."""

    @abstractmethod
    async def read_file(self, path: str) -> bytes:
        """Read and return file content from storage."""

    @abstractmethod
    async def delete_file(self, path: str) -> bool:
        """Delete a stored file. Returns True if deleted, False if not found."""

    @abstractmethod
    async def file_exists(self, path: str) -> bool:
        """Return True if the file exists in storage."""

    @abstractmethod
    def get_url(self, path: str) -> str:
        """Return an accessible URL or filesystem path for the given storage path."""

    @abstractmethod
    async def ensure_directories(self) -> None:
        """Create any required directory / container structure."""

    # Convenience path helpers (each impl may override)
    def raw_path(self, document_id: str, extension: str) -> str:
        return f"raw/{document_id}.{extension}"

    def ocr_path(self, document_id: str) -> str:
        return f"ocr/{document_id}.txt"

    def extracted_path(self, document_id: str) -> str:
        return f"extracted/{document_id}.json"

    def final_path(self, document_id: str, extension: str = "json") -> str:
        return f"final/{document_id}.{extension}"

    def exception_path(self, document_id: str) -> str:
        return f"exceptions/{document_id}.json"

    def processed_path(self, document_id: str, suffix: str = "processed") -> str:
        return f"processed/{document_id}_{suffix}.png"


class LocalStorageAdapter(StorageProviderInterface):
    """
    Thin adapter over the existing LocalStorageProvider.

    Delegates all operations to the legacy implementation. The production guard
    prevents local storage from being used in production deployments.
    """

    provider_name: ClassVar[str] = "local_storage"

    def __init__(
        self,
        base_dir: Optional[str] = None,
        allow_local_in_production: bool = False,
    ) -> None:
        self._base_dir = base_dir
        self._allow_local_in_production = allow_local_in_production
        self._impl = None

    def _get_impl(self):
        if self._impl is None:
            from app.services.storage.local_storage import LocalStorageProvider

            self._impl = LocalStorageProvider(base_dir=self._base_dir)
        return self._impl

    def _guard_production(self) -> None:
        from app.core.config import settings

        env = getattr(settings, "ENVIRONMENT", "development").lower()
        if env == "production" and not self._allow_local_in_production:
            from core.base.exceptions import ProviderException
            raise ProviderException(
                "LocalStorageProvider is not allowed in production. "
                "Configure Azure Blob Storage via StorageConfig.",
                provider_name=self.provider_name,
                operation="guard_production",
            )

    async def health_check(self) -> bool:
        try:
            impl = self._get_impl()
            await impl.ensure_directories()
            return True
        except Exception:
            return False

    async def save_file(self, content: bytes, destination_path: str) -> str:
        self._guard_production()
        return await self._get_impl().save_file(content, destination_path)

    async def read_file(self, path: str) -> bytes:
        return await self._get_impl().read_file(path)

    async def delete_file(self, path: str) -> bool:
        return await self._get_impl().delete_file(path)

    async def file_exists(self, path: str) -> bool:
        return await self._get_impl().file_exists(path)

    def get_url(self, path: str) -> str:
        return self._get_impl().get_url(path)

    async def ensure_directories(self) -> None:
        await self._get_impl().ensure_directories()

    def raw_path(self, document_id: str, extension: str) -> str:
        return self._get_impl().raw_path(document_id, extension)

    def ocr_path(self, document_id: str) -> str:
        return self._get_impl().ocr_path(document_id)

    def extracted_path(self, document_id: str) -> str:
        return self._get_impl().extracted_path(document_id)

    def final_path(self, document_id: str, extension: str = "json") -> str:
        return self._get_impl().final_path(document_id, extension)

    def exception_path(self, document_id: str) -> str:
        return self._get_impl().exception_path(document_id)

    def processed_path(self, document_id: str, suffix: str = "processed") -> str:
        return self._get_impl().processed_path(document_id, suffix)

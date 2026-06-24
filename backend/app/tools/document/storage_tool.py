"""StorageTool — provider-agnostic file storage via injected StorageProviderInterface."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class StorageUploadInput(ToolInput):
    file_bytes: bytes
    document_id: str
    tenant_id: str
    original_filename: str
    content_type: str = "application/pdf"


class StorageUploadOutput(ToolOutput):
    storage_path: Optional[str] = None
    access_url: Optional[str] = None
    size_bytes: int = 0
    provider: str = "unknown"
    error_code: Optional[str] = None


class StorageReadInput(ToolInput):
    storage_path: str
    tenant_id: str = "default"


class StorageReadOutput(ToolOutput):
    file_bytes: Optional[bytes] = None
    size_bytes: int = 0
    error_code: Optional[str] = None


class StorageDeleteInput(ToolInput):
    storage_path: str
    tenant_id: str
    reason: str = "REJECTED"


class StorageDeleteOutput(ToolOutput):
    deleted_path: Optional[str] = None
    error_code: Optional[str] = None


class StorageTool(BaseTool):
    name: ClassVar[str] = "storage"
    description: ClassVar[str] = "Upload, read, and delete files via the configured storage provider"
    input_model: ClassVar = StorageUploadInput
    output_model: ClassVar = StorageUploadOutput

    def __init__(self, storage_provider=None, **kwargs):
        super().__init__(**kwargs)
        self._storage = storage_provider

    def _get_storage(self):
        if self._storage is None:
            from core.container import get_container
            self._storage = get_container().storage_provider
        return self._storage

    def _execute(self, input_data: StorageUploadInput) -> StorageUploadOutput:
        return self.upload(input_data)

    def upload(self, input_data: StorageUploadInput) -> StorageUploadOutput:
        try:
            import asyncio
            storage = self._get_storage()
            now = datetime.now(timezone.utc)
            path = f"{input_data.tenant_id}/{now.year}/{now.month:02d}/{input_data.document_id}/{input_data.original_filename}"

            loop = asyncio.get_event_loop()
            stored_path = loop.run_until_complete(storage.save_file(input_data.file_bytes, path))
            url = storage.get_url(stored_path)
            return StorageUploadOutput(
                success=True,
                storage_path=stored_path,
                access_url=url,
                size_bytes=len(input_data.file_bytes),
                provider=storage.provider_name,
            )
        except Exception as exc:
            return StorageUploadOutput(
                success=False,
                error_code="UPLOAD_FAILED",
                error_message=str(exc),
                size_bytes=0,
            )

    def read(self, input_data: StorageReadInput) -> StorageReadOutput:
        try:
            import asyncio
            storage = self._get_storage()
            loop = asyncio.get_event_loop()
            data = loop.run_until_complete(storage.read_file(input_data.storage_path))
            return StorageReadOutput(success=True, file_bytes=data, size_bytes=len(data))
        except Exception as exc:
            return StorageReadOutput(
                success=False,
                error_code="FILE_NOT_FOUND",
                error_message=str(exc),
            )

    def delete(self, input_data: StorageDeleteInput) -> StorageDeleteOutput:
        try:
            import asyncio
            storage = self._get_storage()
            loop = asyncio.get_event_loop()
            loop.run_until_complete(storage.delete_file(input_data.storage_path))
            return StorageDeleteOutput(success=True, deleted_path=input_data.storage_path)
        except Exception as exc:
            return StorageDeleteOutput(
                success=False,
                error_code="DELETE_FAILED",
                error_message=str(exc),
            )

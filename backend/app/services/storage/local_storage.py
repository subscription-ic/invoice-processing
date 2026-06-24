from __future__ import annotations

import os
from pathlib import Path

import aiofiles

from app.core.config import settings
from app.services.storage.base import StorageProvider


class LocalStorageProvider(StorageProvider):
    """
    Stores files on the local filesystem under settings.UPLOAD_DIR.
    Directory structure:
        /uploads/raw/{document_id}.*
        /uploads/ocr/{document_id}.txt
        /uploads/extracted/{document_id}.json
        /uploads/final/{document_id}.*
        /uploads/exceptions/{document_id}.*
        /uploads/processed/{document_id}.*
    """

    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir or settings.UPLOAD_DIR)
        self._subdirs = ["raw", "ocr", "extracted", "final", "exceptions", "processed"]

    async def ensure_directories(self) -> None:
        for subdir in self._subdirs:
            (self.base_dir / subdir).mkdir(parents=True, exist_ok=True)

    async def save_file(self, content: bytes, destination_path: str) -> str:
        full_path = self.base_dir / destination_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(full_path, "wb") as f:
            await f.write(content)
        return destination_path

    async def read_file(self, path: str) -> bytes:
        full_path = self.base_dir / path if not Path(path).is_absolute() else Path(path)
        async with aiofiles.open(full_path, "rb") as f:
            return await f.read()

    async def delete_file(self, path: str) -> bool:
        full_path = self.base_dir / path if not Path(path).is_absolute() else Path(path)
        try:
            full_path.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    async def file_exists(self, path: str) -> bool:
        full_path = self.base_dir / path if not Path(path).is_absolute() else Path(path)
        return full_path.exists()

    def get_url(self, path: str) -> str:
        full_path = self.base_dir / path if not Path(path).is_absolute() else Path(path)
        return str(full_path)

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


_storage_provider: LocalStorageProvider | None = None


def get_storage() -> LocalStorageProvider:
    global _storage_provider
    if _storage_provider is None:
        _storage_provider = LocalStorageProvider()
    return _storage_provider
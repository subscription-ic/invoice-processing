from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class StorageProvider(ABC):
    """Abstract storage provider. Swap LocalStorageProvider for AzureBlobStorageProvider."""

    @abstractmethod
    async def save_file(self, content: bytes, destination_path: str) -> str:
        """Save raw bytes and return the storage path/URL."""

    @abstractmethod
    async def read_file(self, path: str) -> bytes:
        """Read file content from storage."""

    @abstractmethod
    async def delete_file(self, path: str) -> bool:
        """Delete a file from storage."""

    @abstractmethod
    async def file_exists(self, path: str) -> bool:
        """Check whether a file exists."""

    @abstractmethod
    def get_url(self, path: str) -> str:
        """Return the URL or filesystem path for a stored file."""

    @abstractmethod
    async def ensure_directories(self) -> None:
        """Create required directory structure."""
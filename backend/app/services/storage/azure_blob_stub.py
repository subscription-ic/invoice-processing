from __future__ import annotations

from app.services.storage.base import StorageProvider


class AzureBlobStorageProvider(StorageProvider):
    """
    Future implementation: Azure Blob Storage.
    Install: azure-storage-blob
    """

    def __init__(self, connection_string: str, container_name: str):
        self.connection_string = connection_string
        self.container_name = container_name
        raise NotImplementedError(
            "AzureBlobStorageProvider is not yet implemented. "
            "Use LocalStorageProvider for MVP. "
            "When ready: pip install azure-storage-blob and implement this class."
        )

    async def save_file(self, content: bytes, destination_path: str) -> str:
        raise NotImplementedError

    async def read_file(self, path: str) -> bytes:
        raise NotImplementedError

    async def delete_file(self, path: str) -> bool:
        raise NotImplementedError

    async def file_exists(self, path: str) -> bool:
        raise NotImplementedError

    def get_url(self, path: str) -> str:
        raise NotImplementedError

    async def ensure_directories(self) -> None:
        pass
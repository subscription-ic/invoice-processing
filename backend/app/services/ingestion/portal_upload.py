from __future__ import annotations

from typing import AsyncGenerator

from fastapi import UploadFile

from app.services.ingestion.base import DocumentIngestionProvider, IngestedDocument


class PortalUploadProvider(DocumentIngestionProvider):
    """
    MVP implementation: direct browser portal upload via FastAPI UploadFile.
    The ingest() method is not used in poll mode; documents are ingested
    synchronously on upload via the /api/v1/documents/upload endpoint.
    """

    @property
    def source_name(self) -> str:
        return "PORTAL"

    async def ingest(self) -> AsyncGenerator[IngestedDocument, None]:
        # Portal uploads are push-based, not pull-based.
        return
        yield  # satisfy generator signature

    async def acknowledge(self, document_id: str) -> None:
        pass  # No-op for portal uploads

    async def health_check(self) -> bool:
        return True

    @staticmethod
    async def from_upload(upload_file: UploadFile) -> IngestedDocument:
        content = await upload_file.read()
        return IngestedDocument(
            filename=upload_file.filename or "unknown",
            content=content,
            mime_type=upload_file.content_type or "application/octet-stream",
            metadata={"content_type": upload_file.content_type},
            source="PORTAL",
        )
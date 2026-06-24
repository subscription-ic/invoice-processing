from __future__ import annotations

from typing import AsyncGenerator

from app.services.ingestion.base import DocumentIngestionProvider, IngestedDocument


class EmailIngestionProvider(DocumentIngestionProvider):
    """
    Future: Poll IMAP mailbox and extract invoice attachments.
    Configure via: IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASSWORD
    """

    @property
    def source_name(self) -> str:
        return "EMAIL"

    async def ingest(self) -> AsyncGenerator[IngestedDocument, None]:
        raise NotImplementedError(
            "EmailIngestionProvider not yet implemented. "
            "Future: use imaplib or aioimaplib to poll inbox."
        )
        yield

    async def acknowledge(self, document_id: str) -> None:
        raise NotImplementedError

    async def health_check(self) -> bool:
        return False
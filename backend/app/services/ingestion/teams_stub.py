from __future__ import annotations

from typing import AsyncGenerator

from app.services.ingestion.base import DocumentIngestionProvider, IngestedDocument


class TeamsIngestionProvider(DocumentIngestionProvider):
    """
    Future: Poll Microsoft Teams channels / SharePoint for documents.
    Requires: Microsoft Graph API, TEAMS_TENANT_ID, TEAMS_CLIENT_ID, TEAMS_CLIENT_SECRET
    """

    @property
    def source_name(self) -> str:
        return "TEAMS"

    async def ingest(self) -> AsyncGenerator[IngestedDocument, None]:
        raise NotImplementedError(
            "TeamsIngestionProvider not yet implemented. "
            "Future: use msgraph-sdk-python and poll Teams channels."
        )
        yield

    async def acknowledge(self, document_id: str) -> None:
        raise NotImplementedError

    async def health_check(self) -> bool:
        return False
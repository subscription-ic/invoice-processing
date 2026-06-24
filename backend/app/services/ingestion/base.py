from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator, Optional


@dataclass
class IngestedDocument:
    filename: str
    content: bytes
    mime_type: str
    metadata: dict
    source: str


class DocumentIngestionProvider(ABC):
    """
    Abstract document ingestion provider.
    Implementations: PortalUploadProvider, EmailProvider, TeamsProvider, ERPProvider
    """

    @abstractmethod
    async def ingest(self) -> AsyncGenerator[IngestedDocument, None]:
        """Yield ingested documents from this source."""

    @abstractmethod
    async def acknowledge(self, document_id: str) -> None:
        """Acknowledge that a document has been processed."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is healthy and reachable."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable source name."""
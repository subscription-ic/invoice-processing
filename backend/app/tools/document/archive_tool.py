"""ArchiveTool — move processed documents to long-term archive storage."""
from __future__ import annotations

from typing import ClassVar, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class ArchiveInput(ToolInput):
    document_id: str
    source_path: str
    tenant_id: str = "default"
    archive_reason: str = "PROCESSED"


class ArchiveOutput(ToolOutput):
    archive_path: Optional[str] = None
    archived: bool = False
    error_code: Optional[str] = None


class ArchiveTool(BaseTool[ArchiveInput, ArchiveOutput]):
    name: ClassVar[str] = "archive"
    description: ClassVar[str] = "Move processed documents to archive storage"
    input_model: ClassVar = ArchiveInput
    output_model: ClassVar = ArchiveOutput

    def _execute(self, input_data: ArchiveInput) -> ArchiveOutput:
        archive_path = f"archive/{input_data.tenant_id}/{input_data.document_id}"
        return ArchiveOutput(success=True, archive_path=archive_path, archived=True)

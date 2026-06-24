"""DocumentMetadataTool — extract and normalise document-level metadata."""
from __future__ import annotations

from typing import ClassVar, Dict, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class DocumentMetadataInput(ToolInput):
    file_bytes: bytes
    filename: str
    document_id: str
    detected_mime: str = "application/pdf"


class DocumentMetadataOutput(ToolOutput):
    page_count: int = 0
    author: Optional[str] = None
    creator_software: Optional[str] = None
    creation_date: Optional[str] = None
    is_scanned: bool = True
    language: Optional[str] = None
    metadata: Dict = {}
    error_code: Optional[str] = None


class DocumentMetadataTool(BaseTool[DocumentMetadataInput, DocumentMetadataOutput]):
    name: ClassVar[str] = "document_metadata"
    description: ClassVar[str] = "Extract structural metadata from a document"
    input_model: ClassVar = DocumentMetadataInput
    output_model: ClassVar = DocumentMetadataOutput

    def _execute(self, input_data: DocumentMetadataInput) -> DocumentMetadataOutput:
        if input_data.detected_mime == "application/pdf":
            return self._from_pdf(input_data)
        return DocumentMetadataOutput(
            success=True, page_count=1, is_scanned=True,
            metadata={"filename": input_data.filename, "mime": input_data.detected_mime},
        )

    def _from_pdf(self, input_data) -> DocumentMetadataOutput:
        try:
            import fitz
            doc = fitz.open(stream=input_data.file_bytes, filetype="pdf")
            meta = doc.metadata or {}
            page_count = len(doc)
            # Check for text layer to determine if scanned
            has_text = any(doc[i].get_text().strip() for i in range(min(3, page_count)))
            doc.close()
            return DocumentMetadataOutput(
                success=True,
                page_count=page_count,
                author=meta.get("author"),
                creator_software=meta.get("creator"),
                creation_date=meta.get("creationDate"),
                is_scanned=not has_text,
                metadata=meta,
            )
        except Exception as exc:
            return DocumentMetadataOutput(
                success=False, error_code="METADATA_EXTRACTION_FAILED", error_message=str(exc)
            )

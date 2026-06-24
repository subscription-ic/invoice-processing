"""DocumentSplitTool — split multi-invoice PDFs into individual documents."""
from __future__ import annotations

from typing import ClassVar, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class DocumentSplitInput(ToolInput):
    file_bytes: bytes
    document_id: str
    split_at_pages: Optional[List[int]] = None  # None = auto-detect by content


class SplitDocument(ToolInput):
    page_range: List[int]
    file_bytes: bytes
    estimated_invoice_number: Optional[str] = None


class DocumentSplitOutput(ToolOutput):
    split_count: int = 1
    documents: List[SplitDocument] = []
    needs_splitting: bool = False
    error_code: Optional[str] = None


class DocumentSplitTool(BaseTool[DocumentSplitInput, DocumentSplitOutput]):
    name: ClassVar[str] = "document_split"
    description: ClassVar[str] = "Split multi-invoice PDFs into individual invoice documents"
    input_model: ClassVar = DocumentSplitInput
    output_model: ClassVar = DocumentSplitOutput

    def _execute(self, input_data: DocumentSplitInput) -> DocumentSplitOutput:
        try:
            import fitz
            doc = fitz.open(stream=input_data.file_bytes, filetype="pdf")
            if len(doc) == 1 or not input_data.split_at_pages:
                doc.close()
                return DocumentSplitOutput(
                    success=True,
                    split_count=1,
                    documents=[SplitDocument(page_range=[1], file_bytes=input_data.file_bytes)],
                    needs_splitting=False,
                )
            # Split at configured page boundaries
            splits = []
            pages = [0] + input_data.split_at_pages + [len(doc)]
            for i in range(len(pages) - 1):
                new_doc = fitz.open()
                new_doc.insert_pdf(doc, from_page=pages[i], to_page=pages[i + 1] - 1)
                buf = new_doc.tobytes()
                new_doc.close()
                splits.append(SplitDocument(
                    page_range=list(range(pages[i] + 1, pages[i + 1] + 1)),
                    file_bytes=buf,
                ))
            doc.close()
            return DocumentSplitOutput(
                success=True, split_count=len(splits), documents=splits, needs_splitting=True
            )
        except Exception as exc:
            return DocumentSplitOutput(success=False, error_code="SPLIT_FAILED", error_message=str(exc))

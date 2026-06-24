"""PDFTool — renders PDF pages and extracts structure."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class PDFExtractionInput(ToolInput):
    file_bytes: bytes
    document_id: Optional[str] = None
    render_dpi: int = 300
    extract_images: bool = True
    extract_metadata: bool = True
    max_pages: int = 50


class PDFPage(ToolInput):
    page_number: int
    image_bytes: bytes
    width_px: int
    height_px: int
    has_text_layer: bool
    native_text: Optional[str] = None


class PDFMetadata(ToolInput):
    author: Optional[str] = None
    creator_software: Optional[str] = None
    creation_date: Optional[str] = None
    is_encrypted: bool = False
    pdf_version: Optional[str] = None
    page_count: int = 0


class PDFExtractionOutput(ToolOutput):
    page_count: int = 0
    has_native_text: bool = False
    pages: List[PDFPage] = field(default_factory=list)
    metadata: Optional[PDFMetadata] = None
    error_code: Optional[str] = None


class PDFTool(BaseTool[PDFExtractionInput, PDFExtractionOutput]):
    name: ClassVar[str] = "pdf_extraction"
    description: ClassVar[str] = "Render PDF pages to images and detect native text layer"
    input_model: ClassVar = PDFExtractionInput
    output_model: ClassVar = PDFExtractionOutput

    def _execute(self, input_data: PDFExtractionInput) -> PDFExtractionOutput:
        try:
            import fitz
            from PIL import Image
            import io

            doc = fitz.open(stream=input_data.file_bytes, filetype="pdf")
            page_count = len(doc)
            limit = min(page_count, input_data.max_pages)
            zoom = input_data.render_dpi / 72.0
            matrix = fitz.Matrix(zoom, zoom)

            pages: List[PDFPage] = []
            any_native_text = False

            for i in range(limit):
                page = doc[i]
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                img_bytes = pix.tobytes("png")

                native_text = page.get_text("text").strip() if input_data.extract_images else None
                has_text = bool(native_text)
                if has_text:
                    any_native_text = True

                pages.append(PDFPage(
                    page_number=i + 1,
                    image_bytes=img_bytes,
                    width_px=pix.width,
                    height_px=pix.height,
                    has_text_layer=has_text,
                    native_text=native_text if has_text else None,
                ))

            meta = None
            if input_data.extract_metadata:
                raw = doc.metadata or {}
                meta = PDFMetadata(
                    author=raw.get("author"),
                    creator_software=raw.get("creator"),
                    creation_date=raw.get("creationDate"),
                    is_encrypted=doc.is_encrypted,
                    pdf_version=f"{doc.version}",
                    page_count=page_count,
                )
            doc.close()

            return PDFExtractionOutput(
                success=True,
                page_count=page_count,
                has_native_text=any_native_text,
                pages=pages,
                metadata=meta,
            )
        except Exception as exc:
            return PDFExtractionOutput(
                success=False,
                page_count=0,
                error_code="PDF_CORRUPTED",
                error_message=str(exc),
            )

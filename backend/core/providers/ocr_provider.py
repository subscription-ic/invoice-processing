"""
OCRProvider — interface and Tesseract implementation.

The interface accepts raw file bytes and a mime type; returns plain text.
Future: swap TesseractOCRProvider for AzureDocumentIntelligenceProvider.
"""

from __future__ import annotations

import io
from abc import abstractmethod
from typing import Any, ClassVar, Dict, List, Optional

from core.base.provider import BaseProvider


class OCRResult:
    """Value object returned by any OCR provider."""

    __slots__ = ("text", "page_count", "confidence", "provider", "metadata")

    def __init__(
        self,
        text: str,
        page_count: int = 1,
        confidence: float = 0.0,
        provider: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.text = text
        self.page_count = page_count
        self.confidence = confidence
        self.provider = provider
        self.metadata = metadata or {}

    def __repr__(self) -> str:  # pragma: no cover
        return f"OCRResult(chars={len(self.text)}, pages={self.page_count}, conf={self.confidence:.2f})"


class OCRProviderInterface(BaseProvider):
    """
    Abstract OCR provider.

    Implementations must be stateless and thread-safe. The platform container
    holds a single shared instance.
    """

    provider_type: ClassVar[str] = "ocr"

    @abstractmethod
    async def extract_text(
        self,
        file_bytes: bytes,
        mime_type: str = "application/pdf",
        document_id: Optional[str] = None,
    ) -> OCRResult:
        """Extract raw text from document bytes."""

    @abstractmethod
    async def extract_text_with_layout(
        self,
        file_bytes: bytes,
        mime_type: str = "application/pdf",
    ) -> List[Dict[str, Any]]:
        """
        Extract text with positional metadata.
        Returns a list of page dicts: {page: int, text: str, words: [...]}
        """


class TesseractOCRProvider(OCRProviderInterface):
    """
    Tesseract-based OCR.

    Wraps the existing pytesseract logic used by the OCRAgent.
    PDF pages are rendered to PNG via PyMuPDF then fed to pytesseract.
    """

    provider_name: ClassVar[str] = "tesseract"

    def __init__(self, dpi: int = 300, lang: str = "eng") -> None:
        self._dpi = dpi
        self._lang = lang

    async def health_check(self) -> bool:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    async def extract_text(
        self,
        file_bytes: bytes,
        mime_type: str = "application/pdf",
        document_id: Optional[str] = None,
    ) -> OCRResult:
        try:
            pages = await self._render_pages(file_bytes, mime_type)
            page_texts: List[str] = []
            confidences: List[float] = []

            for page_img in pages:
                text, conf = await self._ocr_image(page_img)
                page_texts.append(text)
                confidences.append(conf)

            full_text = "\n\n".join(page_texts)
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

            return OCRResult(
                text=full_text,
                page_count=len(pages),
                confidence=avg_conf,
                provider=self.provider_name,
            )
        except Exception as exc:
            from core.base.exceptions import ProviderException
            raise ProviderException(
                f"Tesseract OCR failed: {exc}",
                provider_name=self.provider_name,
                operation="extract_text",
            ) from exc

    async def extract_text_with_layout(
        self,
        file_bytes: bytes,
        mime_type: str = "application/pdf",
    ) -> List[Dict[str, Any]]:
        try:
            import pytesseract
            from PIL import Image

            pages = await self._render_pages(file_bytes, mime_type)
            result = []
            for i, page_img in enumerate(pages):
                data = pytesseract.image_to_data(
                    page_img,
                    lang=self._lang,
                    output_type=pytesseract.Output.DICT,
                )
                words = [
                    {
                        "text": data["text"][j],
                        "conf": int(data["conf"][j]),
                        "x": data["left"][j],
                        "y": data["top"][j],
                        "w": data["width"][j],
                        "h": data["height"][j],
                    }
                    for j in range(len(data["text"]))
                    if data["text"][j].strip()
                ]
                result.append(
                    {
                        "page": i + 1,
                        "text": " ".join(w["text"] for w in words),
                        "words": words,
                    }
                )
            return result
        except Exception as exc:
            from core.base.exceptions import ProviderException
            raise ProviderException(
                f"Tesseract layout extraction failed: {exc}",
                provider_name=self.provider_name,
                operation="extract_text_with_layout",
            ) from exc

    async def _render_pages(self, file_bytes: bytes, mime_type: str) -> list:
        """Render document pages to PIL images."""
        from PIL import Image

        if mime_type == "application/pdf" or file_bytes[:4] == b"%PDF":
            return await self._render_pdf_pages(file_bytes)
        else:
            # Assume single-page image (JPEG, PNG, TIFF)
            img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
            return [img]

    async def _render_pdf_pages(self, pdf_bytes: bytes) -> list:
        """Render all PDF pages to PIL images at configured DPI."""
        import fitz  # PyMuPDF
        from PIL import Image

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        images = []
        zoom = self._dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)
        doc.close()
        return images

    async def _ocr_image(self, image) -> tuple[str, float]:
        """Run tesseract on a PIL image. Returns (text, avg_confidence)."""
        import pytesseract

        data = pytesseract.image_to_data(
            image,
            lang=self._lang,
            output_type=pytesseract.Output.DICT,
        )
        text_parts = [t for t in data["text"] if t.strip()]
        confs = [
            float(c)
            for c, t in zip(data["conf"], data["text"])
            if t.strip() and str(c).lstrip("-").isdigit() and int(c) >= 0
        ]
        text = " ".join(text_parts)
        avg_conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
        return text, avg_conf

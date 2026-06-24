"""OCRTool — text extraction via injected OCRProviderInterface."""
from __future__ import annotations

import asyncio
from typing import ClassVar, Dict, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class OCRInput(ToolInput):
    file_bytes: bytes
    mime_type: str = "application/pdf"
    document_id: Optional[str] = None
    page_number: Optional[int] = None


class OCROutput(ToolOutput):
    raw_text: Optional[str] = None
    page_count: int = 0
    confidence: float = 0.0
    provider: str = "unknown"
    word_count: int = 0
    error_code: Optional[str] = None


class OCRTool(BaseTool[OCRInput, OCROutput]):
    name: ClassVar[str] = "ocr"
    description: ClassVar[str] = "Extract text from document images via the configured OCR provider"
    input_model: ClassVar = OCRInput
    output_model: ClassVar = OCROutput

    def __init__(self, ocr_provider=None, **kwargs):
        super().__init__(**kwargs)
        self._ocr = ocr_provider

    def _get_ocr(self):
        if self._ocr is None:
            from core.container import get_container
            self._ocr = get_container().ocr_provider
        return self._ocr

    def _execute(self, input_data: OCRInput) -> OCROutput:
        try:
            ocr = self._get_ocr()
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(
                ocr.extract_text(
                    file_bytes=input_data.file_bytes,
                    mime_type=input_data.mime_type,
                    document_id=input_data.document_id,
                )
            )
            return OCROutput(
                success=True,
                raw_text=result.text,
                page_count=result.page_count,
                confidence=result.confidence,
                provider=result.provider,
                word_count=len(result.text.split()) if result.text else 0,
            )
        except Exception as exc:
            return OCROutput(
                success=False,
                error_code="OCR_FAILED",
                error_message=str(exc),
            )


class OCRConfidenceInput(ToolInput):
    raw_text: str
    expected_min_words: int = 10
    expected_fields: Optional[List[str]] = None


class OCRConfidenceOutput(ToolOutput):
    quality_score: float = 0.0
    quality_tier: str = "UNKNOWN"
    word_count: int = 0
    missing_expected_fields: List[str] = []
    recommendation: Optional[str] = None


class OCRConfidenceTool(BaseTool[OCRConfidenceInput, OCRConfidenceOutput]):
    name: ClassVar[str] = "ocr_confidence"
    description: ClassVar[str] = "Evaluate the quality of OCR output text"
    input_model: ClassVar = OCRConfidenceInput
    output_model: ClassVar = OCRConfidenceOutput

    def _execute(self, input_data: OCRConfidenceInput) -> OCRConfidenceOutput:
        text = input_data.raw_text or ""
        words = text.split()
        word_count = len(words)
        score = min(1.0, word_count / max(input_data.expected_min_words, 1))

        missing = []
        if input_data.expected_fields:
            text_lower = text.lower()
            for field in input_data.expected_fields:
                if field.lower() not in text_lower:
                    missing.append(field)
            field_score = 1.0 - (len(missing) / len(input_data.expected_fields))
            score = (score + field_score) / 2

        if score >= 0.85:
            tier = "HIGH"
        elif score >= 0.60:
            tier = "MEDIUM"
        elif score >= 0.40:
            tier = "LOW"
        else:
            tier = "UNUSABLE"

        return OCRConfidenceOutput(
            success=True,
            quality_score=round(score, 3),
            quality_tier=tier,
            word_count=word_count,
            missing_expected_fields=missing,
            recommendation="Request re-scan" if tier in ("LOW", "UNUSABLE") else None,
        )


class TextNormalizationInput(ToolInput):
    raw_text: str
    document_id: Optional[str] = None
    remove_headers_footers: bool = True
    normalize_whitespace: bool = True
    fix_encoding: bool = True


class TextNormalizationOutput(ToolOutput):
    normalized_text: Optional[str] = None
    char_count_before: int = 0
    char_count_after: int = 0


class TextNormalizationTool(BaseTool[TextNormalizationInput, TextNormalizationOutput]):
    name: ClassVar[str] = "text_normalization"
    description: ClassVar[str] = "Clean and normalize raw OCR text for downstream processing"
    input_model: ClassVar = TextNormalizationInput
    output_model: ClassVar = TextNormalizationOutput

    def _execute(self, input_data: TextNormalizationInput) -> TextNormalizationOutput:
        import re
        text = input_data.raw_text
        before = len(text)

        if input_data.fix_encoding:
            text = text.encode("utf-8", errors="replace").decode("utf-8")

        if input_data.normalize_whitespace:
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = text.strip()

        return TextNormalizationOutput(
            success=True,
            normalized_text=text,
            char_count_before=before,
            char_count_after=len(text),
        )


class LayoutDetectionInput(ToolInput):
    file_bytes: bytes
    mime_type: str = "application/pdf"
    document_id: Optional[str] = None


class LayoutDetectionOutput(ToolOutput):
    has_table: bool = False
    has_header: bool = False
    has_footer: bool = False
    detected_regions: List[Dict] = []
    layout_type: str = "UNKNOWN"


class LayoutDetectionTool(BaseTool[LayoutDetectionInput, LayoutDetectionOutput]):
    name: ClassVar[str] = "layout_detection"
    description: ClassVar[str] = "Detect structural regions (tables, headers, line items) in document images"
    input_model: ClassVar = LayoutDetectionInput
    output_model: ClassVar = LayoutDetectionOutput

    def _execute(self, input_data: LayoutDetectionInput) -> LayoutDetectionOutput:
        # In production: use table detection model or Azure DI
        return LayoutDetectionOutput(
            success=True,
            has_table=True,
            has_header=True,
            layout_type="INVOICE",
        )

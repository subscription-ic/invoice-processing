"""OCRAgent — extract text from scanned documents via the OCR provider."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, Optional

from core.base.agent import BaseAgent
from core.state.workflow_state import WorkflowState


class OCRAgent(BaseAgent):
    name: ClassVar[str] = "ocr_agent"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.ocr.ocr_tool import OCRTool, OCRInput, OCRConfidenceTool, OCRConfidenceInput
        from app.tools.document.image_tool import ImageTool, ImageProcessingInput
        from app.tools.document.storage_tool import StorageTool, StorageReadInput
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
        from app.tools.workflow.exception_tool import ExceptionTool, ExceptionInput

        ocr_tool = OCRTool()
        image_tool = ImageTool()
        confidence_tool = OCRConfidenceTool()
        storage_tool = StorageTool()
        audit_tool = AuditTool()
        exception_tool = ExceptionTool()

        doc_id = state.workflow.document_id
        storage_path = state.document.storage_path
        mime = state.document.mime_type or "application/pdf"

        if not storage_path:
            return state.with_error("NO_STORAGE_PATH", "No storage path for OCR", self.name)

        read_result = storage_tool.read(StorageReadInput(storage_path=storage_path, document_id=doc_id))
        if not read_result.success or not read_result.file_bytes:
            return state.with_error("STORAGE_READ_FAILED", "Cannot load file for OCR", self.name)

        file_bytes = read_result.file_bytes

        # Enhance image quality before OCR
        if "image" in mime:
            img_result = image_tool.run(ImageProcessingInput(
                image_bytes=file_bytes,
                document_id=doc_id,
            ))
            if img_result.success and img_result.processed_image_bytes:
                file_bytes = img_result.processed_image_bytes

        ocr_result = ocr_tool.run(OCRInput(
            file_bytes=file_bytes,
            mime_type=mime,
            document_id=doc_id,
        ))

        if not ocr_result.success or not ocr_result.raw_text:
            return state.with_error("OCR_FAILED", ocr_result.error_message or "OCR returned no text", self.name)

        min_words = self._config.get("ocr.min_word_count", 10)
        conf_result = confidence_tool.run(OCRConfidenceInput(
            raw_text=ocr_result.raw_text,
            expected_min_words=min_words,
        ))

        audit_tool.run(AuditEventInput(
            document_id=doc_id,
            entity_type="DOCUMENT",
            entity_id=doc_id,
            action="OCR_COMPLETED",
            agent_name=self.name,
            after_state={
                "confidence": ocr_result.confidence,
                "quality_tier": conf_result.quality_tier,
                "word_count": ocr_result.word_count,
            },
            stage="OCR",
        ))

        if conf_result.quality_tier in ("UNUSABLE", "LOW"):
            ex_result = exception_tool.run(ExceptionInput(
                document_id=doc_id,
                exception_type="OCR_LOW_CONFIDENCE",
                severity="HIGH",
                queue="AP_TEAM",
                description=f"OCR quality {conf_result.quality_tier} — score {conf_result.quality_score:.2f}",
                agent_name=self.name,
            ))
            return state.model_copy(deep=True, update={
                "exception": state.exception.model_copy(update={
                    "exception_id": ex_result.exception_id,
                    "exception_type": "OCR_LOW_CONFIDENCE",
                    "assigned_queue": "AP_TEAM",
                    "severity": "HIGH",
                }),
                "routing": state.routing.model_copy(update={"requires_human_review": True}),
                "workflow": state.workflow.model_copy(update={
                    "status": "HUMAN_REVIEW_REQUIRED",
                    "current_agent": self.name,
                    "updated_at": datetime.now(timezone.utc),
                }),
            })

        return state.model_copy(deep=True, update={
            "ocr": state.ocr.model_copy(update={
                "raw_text": ocr_result.raw_text,
                "avg_confidence": ocr_result.confidence,
                "page_count": ocr_result.page_count,
                "word_count": ocr_result.word_count,
                "provider_used": "TESSERACT",
                "low_confidence": conf_result.quality_tier in ("MEDIUM", "LOW"),
            }),
            "workflow": state.workflow.model_copy(update={
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

"""ClassificationAgent — classify document type (DIGITAL/SCANNED) and business profile."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, Optional

from core.base.agent import BaseAgent
from core.state.workflow_state import WorkflowState


class ClassificationAgent(BaseAgent):
    name: ClassVar[str] = "classification_agent"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.document.pdf_tool import PDFTool, PDFExtractionInput
        from app.tools.document.image_tool import ImageTool, ImageProcessingInput
        from app.tools.document.storage_tool import StorageTool, StorageReadInput
        from app.tools.ai.classification_tool import ClassificationTool, ClassificationInput
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

        pdf_tool = PDFTool()
        image_tool = ImageTool()
        storage_tool = StorageTool()
        classification_tool = ClassificationTool()
        audit_tool = AuditTool()

        doc_id = state.workflow.document_id
        storage_path = state.document.storage_path
        mime = state.document.mime_type or "application/pdf"

        if not storage_path:
            return state.with_error("NO_STORAGE_PATH", "Document has no storage path", self.name)

        read_result = storage_tool.read(StorageReadInput(storage_path=storage_path, document_id=doc_id))
        if not read_result.success or not read_result.file_bytes:
            return state.with_error("STORAGE_READ_FAILED", "Cannot load file for classification", self.name)

        file_bytes = read_result.file_bytes
        raw_text = ""
        page_image: Optional[bytes] = None
        is_digital = False

        if "pdf" in mime:
            pdf_result = pdf_tool.run(PDFExtractionInput(
                file_bytes=file_bytes,
                document_id=doc_id,
                render_dpi=150,
            ))
            if pdf_result.success:
                is_digital = pdf_result.has_native_text
                if is_digital:
                    raw_text = "\n".join(
                        p.native_text for p in pdf_result.pages if p.native_text
                    )
                if pdf_result.pages:
                    page_image = pdf_result.pages[0].image_bytes
        else:
            img_result = image_tool.run(ImageProcessingInput(
                image_bytes=file_bytes,
                document_id=doc_id,
            ))
            if img_result.success:
                page_image = img_result.processed_image_bytes

        cls_result = classification_tool.run(ClassificationInput(
            raw_text=raw_text or "",
            document_id=doc_id,
            page_image=page_image,
            filename=state.document.original_filename,
        ))

        doc_class = "DIGITAL" if is_digital else "SCANNED"

        audit_tool.run(AuditEventInput(
            document_id=doc_id,
            entity_type="DOCUMENT",
            entity_id=doc_id,
            action="DOCUMENT_CLASSIFIED",
            agent_name=self.name,
            after_state={
                "document_class": doc_class,
                "business_profile": cls_result.business_profile,
                "confidence": cls_result.confidence,
            },
            stage="DOCUMENT_CLASSIFICATION",
        ))

        return state.model_copy(deep=True, update={
            "classification": state.classification.model_copy(update={
                "document_class": doc_class,
                "ocr_strategy": "BYPASS" if is_digital else "TESSERACT",
                "confidence": cls_result.confidence,
            }),
            "profile": state.profile.model_copy(update={
                "business_profile": cls_result.business_profile,
                "profile_confidence": cls_result.confidence,
                "profile_reasoning": cls_result.reasoning,
                "classification_method": "AI",
            }),
            "ocr": state.ocr.model_copy(update={
                "raw_text": raw_text or None,
                "provider_used": "BYPASS" if is_digital else None,
            }),
            "workflow": state.workflow.model_copy(update={
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

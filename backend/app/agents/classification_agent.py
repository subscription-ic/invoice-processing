from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.agents.base import AgentState, BaseAgent
from app.core.config import settings
from app.models.models import Document, DocumentStatus, DocType, ProcessingStage
from app.tools.audit_tool import log_audit, update_workflow_stage
from app.tools.image_quality import analyze_image_quality
from app.tools.pdf_analyzer import analyze_pdf, pdf_page_to_image


class ClassificationAgent(BaseAgent):
    """
    Agent 2: DOCUMENT CLASSIFICATION
    Determines: DIGITAL | SCANNED | HANDWRITTEN
    Routes to OCR or directly to Extraction.
    Does NOT predict business profile.
    """

    name = "CLASSIFICATION_AGENT"
    progress_on_entry = 8
    progress_on_exit = 20

    def _execute(self, state: AgentState) -> AgentState:
        document_id: str = state["document_id"]
        file_path: str = state["file_path"]
        ext: str = state.get("file_extension", "").lower()

        doc = self.db.query(Document).filter(Document.id == document_id).first()

        # ── Step 1: Determine doc_type from extension ─────────────────────────
        if ext == "docx":
            doc_type = DocType.DIGITAL
            state["doc_type"] = doc_type
            state["ocr_text"] = self._extract_docx_text(file_path)
            return self._route_to_extraction(state, doc, doc_type, "DOCX file is always DIGITAL", {})

        if ext in ("jpg", "jpeg", "png", "tiff", "tif"):
            return self._process_image_file(state, doc, file_path)

        if ext == "pdf":
            return self._process_pdf(state, doc, file_path)

        # Fallback
        state.set_status("FAILED")
        state.set_error(f"Unsupported extension: {ext}")
        return state

    def _process_pdf(self, state: AgentState, doc: Document, file_path: str) -> AgentState:
        with open(file_path, "rb") as f:
            content = f.read()

        analysis = analyze_pdf(content)

        log_audit(
            self.db,
            document_id=state["document_id"],
            entity_type="DOCUMENT",
            action="PDF_ANALYZED",
            agent=self.name,
            after_state={
                "doc_type": analysis.doc_type,
                "confidence": analysis.confidence,
                "total_text_length": analysis.total_text_length,
                "pages_with_text": analysis.pages_with_text,
            },
            stage=ProcessingStage.DOCUMENT_CLASSIFICATION,
        )

        if analysis.doc_type == DocType.DIGITAL:
            state["ocr_text"] = analysis.full_text
            return self._route_to_extraction(state, doc, DocType.DIGITAL, analysis.reason, {
                "pdf_analysis": {
                    "doc_type": analysis.doc_type,
                    "text_length": analysis.total_text_length,
                    "pages": analysis.total_pages,
                    "confidence": analysis.confidence,
                }
            })

        # Scanned PDF — convert first page to image and run image analysis
        image_bytes = pdf_page_to_image(content, page_num=0)
        return self._process_image_bytes(state, doc, image_bytes)

    def _process_image_file(self, state: AgentState, doc: Document, file_path: str) -> AgentState:
        with open(file_path, "rb") as f:
            image_bytes = f.read()
        return self._process_image_bytes(state, doc, image_bytes)

    def _process_image_bytes(self, state: AgentState, doc: Document, image_bytes: bytes) -> AgentState:
        document_id = state["document_id"]

        # ── Image Quality Check ────────────────────────────────────────────────
        quality_report = analyze_image_quality(image_bytes)

        log_audit(
            self.db,
            document_id=document_id,
            entity_type="DOCUMENT",
            action="IMAGE_QUALITY_CHECKED",
            agent=self.name,
            after_state={
                "overall_quality": quality_report.overall_quality,
                "is_acceptable": quality_report.is_acceptable,
                "blur_variance": quality_report.blur_variance,
                "mean_brightness": quality_report.mean_brightness,
                "skew_angle": quality_report.skew_angle,
                "issues": quality_report.issues,
            },
            stage=ProcessingStage.DOCUMENT_CLASSIFICATION,
        )

        doc.image_quality_report = {
            "overall_quality": quality_report.overall_quality,
            "blur_variance": quality_report.blur_variance,
            "mean_brightness": quality_report.mean_brightness,
            "skew_angle": quality_report.skew_angle,
            "snr": quality_report.signal_to_noise_ratio,
            "issues": quality_report.issues,
        }
        self.db.flush()

        if not quality_report.is_acceptable:
            return self._route_to_exception(
                state, doc,
                exception_type="IMAGE_QUALITY_FAILURE",
                description=f"Image quality POOR: {'; '.join(quality_report.issues)}",
                recommendations=quality_report.recommendations,
            )

        # ── Handwriting Detection ──────────────────────────────────────────────
        prompt = self.load_prompt("handwriting")
        result = self._call_openai_vision_json(
            system_prompt=prompt["system_prompt"],
            user_prompt=prompt["user_prompt_template"],
            image_bytes=image_bytes,
            model=prompt["model"],
        )

        handwritten_pct = result.get("handwritten_percentage", 0)
        printed_pct = result.get("printed_percentage", 100)
        hw_confidence = result.get("confidence", 0.8)

        doc_type = DocType.HANDWRITTEN if handwritten_pct > 40 else DocType.SCANNED

        log_audit(
            self.db,
            document_id=document_id,
            entity_type="DOCUMENT",
            action="HANDWRITING_DETECTED",
            agent=self.name,
            after_state={
                "doc_type": doc_type,
                "handwritten_pct": handwritten_pct,
                "printed_pct": printed_pct,
                "confidence": hw_confidence,
            },
            stage=ProcessingStage.DOCUMENT_CLASSIFICATION,
        )

        state["doc_type"] = doc_type
        state["image_bytes"] = image_bytes
        state["handwriting_result"] = result
        doc.doc_type = doc_type
        self.db.flush()

        update_workflow_stage(
            self.db,
            document_id=document_id,
            stage=ProcessingStage.OCR,
            agent=self.name,
            progress_percent=20,
        )

        state.set_status("SUCCESS")
        # Handwritten documents go to the dedicated HandwritingAgent (GPT-4o Vision
        # combined OCR + extraction). Scanned docs use the standard OCR_AGENT path.
        state.set_next_agent("HANDWRITING_AGENT" if doc_type == DocType.HANDWRITTEN else "OCR_AGENT")
        return state

    def _route_to_extraction(self, state: AgentState, doc: Document, doc_type: str, reason: str, details: dict) -> AgentState:
        document_id = state["document_id"]
        doc.doc_type = doc_type
        self.db.flush()

        update_workflow_stage(
            self.db,
            document_id=document_id,
            stage=ProcessingStage.EXTRACTION,
            agent=self.name,
            progress_percent=35,
        )
        state["doc_type"] = doc_type
        state.set_status("SUCCESS")
        state.set_next_agent("EXTRACTION_AGENT")
        return state

    def _route_to_exception(self, state: AgentState, doc: Document, exception_type: str, description: str, recommendations: list) -> AgentState:
        from app.models.models import Exception as Ex, ExceptionStatus, ExceptionSeverity, ExceptionQueue
        document_id = state["document_id"]

        ex = Ex(
            document_id=document_id,
            exception_code=exception_type,
            exception_type=exception_type,
            severity=ExceptionSeverity.HIGH,
            queue=ExceptionQueue.AP_TEAM,
            title=f"Document Quality Issue: {exception_type}",
            description=description,
            agent_raised_by=self.name,
            status=ExceptionStatus.OPEN,
            sla_hours=settings.SLA_AP_TEAM_HOURS,
        )
        self.db.add(ex)

        doc.status = DocumentStatus.HUMAN_REVIEW_REQUIRED
        self.db.flush()

        update_workflow_stage(
            self.db,
            document_id=document_id,
            stage=ProcessingStage.EXCEPTION,
            agent=self.name,
            progress_percent=20,
            error_message=description,
        )

        state.set_status("HUMAN_REVIEW_REQUIRED")
        state.set_next_agent("EXCEPTION_AGENT")
        state["exception_type"] = exception_type
        return state

    @staticmethod
    def _extract_docx_text(file_path: str) -> str:
        try:
            from app.tools.pdf_analyzer import extract_docx_text
            with open(file_path, "rb") as f:
                return extract_docx_text(f.read())
        except Exception:
            return ""
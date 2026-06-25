from __future__ import annotations

import threading
from pathlib import Path

from PIL import Image
import io

# Tesseract is optional — if the native binary isn't installed we fall back
# to GPT-4o Vision OCR (works for scanned and handwritten alike).
try:
    import pytesseract
    from app.core.config import settings as _settings
    # Use explicit path from config if provided (Windows), else rely on PATH
    if _settings.TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = _settings.TESSERACT_CMD
    pytesseract.get_tesseract_version()
    _HAS_TESSERACT = True
except Exception:
    pytesseract = None  # type: ignore
    _HAS_TESSERACT = False

# pytesseract on Windows spawns the Tesseract binary as a subprocess using a
# temp file. Concurrent calls can collide on that temp path. Serialise OCR runs.
_tesseract_lock = threading.Lock()

from sqlalchemy.orm import Session

from app.agents.base import AgentState, BaseAgent
from app.core.config import settings
from app.models.models import Document, DocumentStatus, DocType, ProcessingStage
from app.services.storage.local_storage import get_storage
from app.tools.audit_tool import log_audit, update_workflow_stage
from app.tools.image_quality import preprocess_image


class OCRAgent(BaseAgent):
    """
    Agent 3: OCR
    Runs on SCANNED and HANDWRITTEN documents only.
    DIGITAL documents skip this agent.

    SCANNED: pytesseract
    HANDWRITTEN: GPT-4o Vision
    """

    name = "OCR_AGENT"
    progress_on_entry = 20
    progress_on_exit = 35

    def _execute(self, state: AgentState) -> AgentState:
        document_id: str = state["document_id"]
        doc_type: str = state.get("doc_type", DocType.SCANNED)
        image_bytes: bytes = state.get("image_bytes", b"")

        doc = self.db.query(Document).filter(Document.id == document_id).first()

        if not image_bytes:
            # Load from file path
            file_path = state.get("file_path", "")
            if file_path and Path(file_path).exists():
                with open(file_path, "rb") as f:
                    image_bytes = f.read()

        if not image_bytes:
            state.set_status("FAILED")
            state.set_error("No image content available for OCR")
            return state

        # ── Preprocess ─────────────────────────────────────────────────────────
        processed_bytes = preprocess_image(image_bytes)

        # ── OCR ────────────────────────────────────────────────────────────────
        # Handwritten always uses Vision. Scanned uses Tesseract when available,
        # but falls back to GPT-4o Vision if Tesseract confidence is low — this
        # handles non-Latin scripts (Hindi, Marathi, Arabic, Chinese, etc.) that
        # Tesseract cannot read without the matching language data files installed.
        if doc_type == DocType.HANDWRITTEN:
            ocr_text, ocr_confidence = self._handwritten_ocr(image_bytes)
        elif _HAS_TESSERACT:
            ocr_text, ocr_confidence = self._tesseract_ocr(processed_bytes)
            # Low Tesseract confidence often means non-Latin script → retry with GPT-4o Vision
            if ocr_confidence < settings.OCR_CONFIDENCE_WARNING:
                vision_text, vision_confidence = self._handwritten_ocr(image_bytes)
                if vision_confidence > ocr_confidence:
                    ocr_text, ocr_confidence = vision_text, vision_confidence
        else:
            ocr_text, ocr_confidence = self._handwritten_ocr(image_bytes)

        log_audit(
            self.db,
            document_id=document_id,
            entity_type="DOCUMENT",
            action="OCR_COMPLETED",
            agent=self.name,
            after_state={
                "doc_type": doc_type,
                "ocr_confidence": ocr_confidence,
                "text_length": len(ocr_text),
            },
            stage=ProcessingStage.OCR,
        )

        # ── Confidence Gate ────────────────────────────────────────────────────
        if ocr_confidence < settings.OCR_CONFIDENCE_WARNING:
            # FAIL
            return self._route_to_exception(state, doc, ocr_confidence, ocr_text)

        # Save OCR text to file
        storage = get_storage()
        ocr_rel_path = storage.ocr_path(doc.document_id)
        ocr_full_path = str(Path(settings.UPLOAD_DIR) / ocr_rel_path)
        Path(ocr_full_path).parent.mkdir(parents=True, exist_ok=True)
        with open(ocr_full_path, "w", encoding="utf-8") as f:
            f.write(ocr_text)

        # Save processed image
        processed_rel = storage.processed_path(doc.document_id)
        processed_full = str(Path(settings.UPLOAD_DIR) / processed_rel)
        Path(processed_full).parent.mkdir(parents=True, exist_ok=True)
        with open(processed_full, "wb") as f:
            f.write(processed_bytes)

        doc.ocr_path = ocr_full_path
        doc.ocr_text = ocr_text
        doc.ocr_confidence = ocr_confidence
        self.db.flush()

        update_workflow_stage(
            self.db,
            document_id=document_id,
            stage=ProcessingStage.EXTRACTION,
            agent=self.name,
            progress_percent=35,
            stage_details={
                "ocr_confidence": float(ocr_confidence),
                "text_length": len(ocr_text),
                "confidence_level": "PASS" if ocr_confidence >= settings.OCR_CONFIDENCE_PASS else "WARNING",
            },
        )

        state["ocr_text"] = ocr_text
        state["ocr_confidence"] = ocr_confidence
        state.set_status("SUCCESS")
        state.set_next_agent("EXTRACTION_AGENT")
        return state

    def _tesseract_ocr(self, image_bytes: bytes) -> tuple[str, float]:
        img = Image.open(io.BytesIO(image_bytes))
        with _tesseract_lock:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, lang="eng")

        texts = []
        confidences = []
        for i, conf in enumerate(data["conf"]):
            if conf != -1 and conf > 0:
                texts.append(data["text"][i])
                confidences.append(int(conf))

        full_text = " ".join(t for t in texts if t.strip())
        avg_confidence = sum(confidences) / len(confidences) / 100 if confidences else 0.0
        return full_text, avg_confidence

    def _handwritten_ocr(self, image_bytes: bytes) -> tuple[str, float]:
        prompt = self.load_prompt("handwriting_ocr")
        transcribed = self._call_openai_vision_text(
            system_prompt=prompt["system_prompt"],
            user_prompt=prompt["user_prompt_template"],
            image_bytes=image_bytes,
            model=prompt["model"],
        )
        confidence = 0.80 if transcribed and "[ILLEGIBLE]" not in transcribed else 0.65
        return transcribed, confidence

    def _route_to_exception(self, state: AgentState, doc: Document, confidence: float, ocr_text: str) -> AgentState:
        from app.models.models import Exception as Ex, ExceptionStatus, ExceptionSeverity, ExceptionQueue
        document_id = state["document_id"]

        ex = Ex(
            document_id=document_id,
            exception_code="OCR_LOW_CONFIDENCE",
            exception_type="OCR_LOW_CONFIDENCE",
            severity=ExceptionSeverity.HIGH,
            queue=ExceptionQueue.AP_TEAM,
            title="OCR Low Confidence",
            description=f"OCR confidence {confidence:.0%} is below threshold {settings.OCR_CONFIDENCE_WARNING:.0%}",
            agent_raised_by=self.name,
            status=ExceptionStatus.OPEN,
            sla_hours=settings.SLA_AP_TEAM_HOURS,
        )
        self.db.add(ex)
        doc.status = DocumentStatus.HUMAN_REVIEW_REQUIRED
        doc.ocr_confidence = confidence
        doc.ocr_text = ocr_text
        self.db.flush()

        update_workflow_stage(
            self.db,
            document_id=document_id,
            stage=ProcessingStage.EXCEPTION,
            agent=self.name,
            progress_percent=35,
            error_message=f"OCR confidence {confidence:.0%} too low",
        )

        state.set_status("HUMAN_REVIEW_REQUIRED")
        state.set_next_agent("EXCEPTION_AGENT")
        state["exception_type"] = "OCR_LOW_CONFIDENCE"
        return state
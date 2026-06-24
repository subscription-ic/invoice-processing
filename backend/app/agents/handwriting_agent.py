from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.agents.base import AgentState, BaseAgent
from app.core.config import settings
from app.models.models import Document, DocumentLineItem, DocumentStatus, ProcessingStage, Vendor
from app.services.storage.local_storage import get_storage
from app.tools.audit_tool import log_audit, update_workflow_stage


class HandwritingAgent(BaseAgent):
    """
    Agent 3b: HANDWRITING VISION EXTRACTION

    Dedicated agent for handwritten challans, kachha bills, delivery notes,
    and poor-quality scanned documents that Tesseract cannot reliably read.

    Uses GPT-4o Vision to perform COMBINED OCR + data extraction in a single
    pass — preserving spatial layout and context that is lost when transcribing
    handwriting to raw text first. Replaces the OCR_AGENT → EXTRACTION_AGENT
    two-step for documents classified as HANDWRITTEN.

    On success: populates all document fields and routes to UNIVERSAL_VALIDATION.
    Only falls back to EXCEPTION if the image is truly unreadable (confidence < 0.30
    or explicitly flagged as blank/illegible by the model).
    """

    name = "HANDWRITING_AGENT"
    progress_on_entry = 20
    progress_on_exit = 50

    def _execute(self, state: AgentState) -> AgentState:
        document_id: str = state["document_id"]
        image_bytes: bytes = state.get("image_bytes", b"")
        doc_type: str = state.get("doc_type", "HANDWRITTEN")

        doc = self.db.query(Document).filter(Document.id == document_id).first()

        # Load image from disk if not in state (e.g. PDF path)
        if not image_bytes:
            file_path: str = state.get("file_path", "")
            if file_path and Path(file_path).exists():
                with open(file_path, "rb") as f:
                    raw = f.read()
                if file_path.lower().endswith(".pdf"):
                    from app.tools.pdf_analyzer import pdf_page_to_image
                    image_bytes = pdf_page_to_image(raw, page_num=0)
                else:
                    image_bytes = raw

        if not image_bytes:
            state.set_status("FAILED")
            state.set_error("No image content available for handwriting extraction")
            return state

        # ── GPT-4o Vision Extraction ────────────────────────────────────────────
        prompt = self.load_prompt("handwriting_extraction")
        extracted: Dict[str, Any] = self._call_openai_vision_json(
            system_prompt=prompt["system_prompt"],
            user_prompt=prompt["user_prompt_template"],
            image_bytes=image_bytes,
            model=prompt.get("model", "gpt-4o"),
        )

        meta = extracted.get("_meta") or {}
        vision_confidence: float = float(meta.get("extraction_confidence", 0.7))
        is_unreadable: bool = bool(meta.get("is_unreadable", False))

        # Route to exception only if truly illegible (not just imperfect handwriting)
        if is_unreadable or vision_confidence < 0.30:
            return self._route_to_exception(state, doc, vision_confidence)

        # ── Persist OCR text (verbatim transcription from Vision model) ─────────
        ocr_text: str = meta.get("transcribed_text") or json.dumps(extracted, indent=2, default=str)
        doc.ocr_text = ocr_text
        doc.ocr_confidence = vision_confidence

        log_audit(
            self.db,
            document_id=document_id,
            entity_type="DOCUMENT",
            action="HANDWRITING_EXTRACTED",
            agent=self.name,
            after_state={
                "doc_type": doc_type,
                "vision_confidence": vision_confidence,
                "fields_extracted": list(extracted.keys()),
                "doc_type_detected": meta.get("document_type"),
            },
            stage=ProcessingStage.OCR,
        )

        # ── Populate document fields (same as ExtractionAgent) ──────────────────
        self._populate_document(doc, extracted)
        self._save_line_items(doc, extracted.get("line_items", []))

        # ── Vendor lookup (GSTIN → PAN → name) ─────────────────────────────────
        vendor_data = extracted.get("vendor") or {}
        vendor = None
        if vendor_data.get("gstin"):
            vendor = self.db.query(Vendor).filter(Vendor.gstin == vendor_data["gstin"]).first()
        if not vendor and vendor_data.get("pan"):
            vendor = self.db.query(Vendor).filter(Vendor.pan == vendor_data["pan"]).first()
        if not vendor and vendor_data.get("name"):
            vendor = self.db.query(Vendor).filter(
                Vendor.name.ilike(vendor_data["name"].strip())
            ).first()
        if vendor:
            doc.vendor_id = vendor.id

        # ── Save extracted JSON ─────────────────────────────────────────────────
        storage = get_storage()
        extracted_rel = storage.extracted_path(doc.document_id)
        extracted_full = str(Path(settings.UPLOAD_DIR) / extracted_rel)
        Path(extracted_full).parent.mkdir(parents=True, exist_ok=True)
        with open(extracted_full, "w", encoding="utf-8") as f:
            json.dump(extracted, f, indent=2, default=str)

        doc.extracted_path = extracted_full
        doc.extracted_data = extracted
        self.db.flush()

        # Write an EXTRACTION stage entry so the pipeline strip shows both
        # OCR and EXTRACTION as completed (this agent handled both in one pass).
        update_workflow_stage(
            self.db,
            document_id=document_id,
            stage=ProcessingStage.EXTRACTION,
            agent=self.name,
            progress_percent=50,
            stage_details={
                "mode": "vision_direct",
                "confidence": vision_confidence,
                "document_type": meta.get("document_type"),
            },
        )

        state["extracted_data"] = extracted
        state["ocr_text"] = ocr_text
        state["ocr_confidence"] = vision_confidence
        state["document_language"] = meta.get("document_language", "English")
        state["document_language_code"] = meta.get("document_language_code", "en")
        state["is_indian_document"] = meta.get("is_indian_document", True)
        state.set_status("SUCCESS")
        state.set_next_agent("UNIVERSAL_VALIDATION_AGENT")
        return state

    def _populate_document(self, doc: Document, data: Dict[str, Any]) -> None:
        invoice = data.get("invoice") or {}
        amounts = data.get("amounts") or {}
        refs = data.get("references") or {}

        doc.invoice_number = invoice.get("invoice_number")
        if invoice.get("invoice_date"):
            try:
                doc.invoice_date = datetime.strptime(invoice["invoice_date"], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass

        doc.invoice_amount = self._to_decimal(amounts.get("subtotal"))
        doc.tax_amount = self._to_decimal(amounts.get("total_tax"))
        doc.total_amount = self._to_decimal(amounts.get("total_amount"))
        if invoice.get("currency"):
            doc.currency = invoice["currency"]

        if refs.get("po_number"):
            from app.models.models import PurchaseOrder
            po = self.db.query(PurchaseOrder).filter(
                PurchaseOrder.po_number == refs["po_number"]
            ).first()
            if po:
                doc.po_id = po.id
                if not doc.vendor_id:
                    doc.vendor_id = po.vendor_id
            else:
                refs.pop("po_number", None)
                if isinstance(data.get("references"), dict):
                    data["references"].pop("po_number", None)

        if refs.get("grn_number"):
            from app.models.models import GRN
            grn = self.db.query(GRN).filter(GRN.grn_number == refs["grn_number"]).first()
            if grn:
                doc.grn_id = grn.id

    def _save_line_items(self, doc: Document, line_items: List[Dict[str, Any]]) -> None:
        for i, item in enumerate(line_items or [], start=1):
            li = DocumentLineItem(
                document_id=doc.id,
                line_number=item.get("line_number", i),
                item_code=item.get("item_code"),
                description=item.get("description"),
                hsn_sac_code=item.get("hsn_sac_code"),
                quantity=self._to_decimal(item.get("quantity")),
                unit_price=self._to_decimal(item.get("unit_price")),
                uom=item.get("uom", "KG"),
                discount_amount=self._to_decimal(item.get("discount_amount")) or Decimal("0"),
                cgst_rate=self._to_decimal(item.get("cgst_rate")) or Decimal("0"),
                sgst_rate=self._to_decimal(item.get("sgst_rate")) or Decimal("0"),
                igst_rate=self._to_decimal(item.get("igst_rate")) or Decimal("0"),
                cgst_amount=self._to_decimal(item.get("cgst_amount")) or Decimal("0"),
                sgst_amount=self._to_decimal(item.get("sgst_amount")) or Decimal("0"),
                igst_amount=self._to_decimal(item.get("igst_amount")) or Decimal("0"),
                total_amount=self._to_decimal(item.get("total_amount")),
            )
            self.db.add(li)

    def _route_to_exception(self, state: AgentState, doc: Document, confidence: float) -> AgentState:
        from app.models.models import Exception as Ex, ExceptionStatus, ExceptionSeverity, ExceptionQueue
        document_id = state["document_id"]

        ex = Ex(
            document_id=document_id,
            exception_code="HANDWRITING_UNREADABLE",
            exception_type="HANDWRITING_UNREADABLE",
            severity=ExceptionSeverity.HIGH,
            queue=ExceptionQueue.AP_TEAM,
            title="Handwritten Document Unreadable",
            description=(
                f"GPT-4o Vision could not reliably extract data from this handwritten/scanned document "
                f"(confidence {confidence:.0%}). Manual data entry required."
            ),
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
            progress_percent=25,
            error_message=f"Handwritten document unreadable (confidence {confidence:.0%})",
        )

        state.set_status("HUMAN_REVIEW_REQUIRED")
        state.set_next_agent("EXCEPTION_AGENT")
        state["exception_type"] = "HANDWRITING_UNREADABLE"
        return state

    @staticmethod
    def _to_decimal(value: Any) -> Optional[Decimal]:
        if value is None:
            return None
        try:
            cleaned = str(value).replace(",", "").replace(" ", "").strip()
            return Decimal(cleaned)
        except (InvalidOperation, ValueError):
            return None

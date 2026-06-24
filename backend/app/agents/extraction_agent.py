from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.agents.base import AgentState, BaseAgent
from app.core.config import settings
from app.models.models import Document, DocumentLineItem, ProcessingStage, Vendor
from app.services.storage.local_storage import get_storage
from app.tools.audit_tool import log_audit, update_workflow_stage


class ExtractionAgent(BaseAgent):
    """
    Agent 4: EXTRACTION
    Uses GPT-4o to extract structured data from OCR text / digital PDF text.
    Normalizes dates, amounts, and currencies.
    Saves extracted JSON and populates document fields.
    """

    name = "EXTRACTION_AGENT"
    progress_on_entry = 35
    progress_on_exit = 50

    def _execute(self, state: AgentState) -> AgentState:
        document_id: str = state["document_id"]
        ocr_text: str = state.get("ocr_text", "")

        doc = self.db.query(Document).filter(Document.id == document_id).first()

        if not ocr_text and doc.ocr_text:
            ocr_text = doc.ocr_text

        if not ocr_text:
            state.set_status("FAILED")
            state.set_error("No text available for extraction")
            return state

        # ── Call GPT-4o for extraction ─────────────────────────────────────────
        prompt = self.load_prompt("extraction")
        # Use replace (not .format) — the template contains literal JSON braces
        user_prompt = prompt["user_prompt_template"].replace("{document_text}", ocr_text[:8000])

        extracted: Dict[str, Any] = self._call_openai_json(
            system_prompt=prompt["system_prompt"],
            user_prompt=user_prompt,
            model=prompt["model"],
            temperature=float(prompt.get("temperature", 0.0)),
            max_tokens=int(prompt.get("max_tokens", 4096)),
        )

        # ── Deterministic GSTIN/PAN cross-correction ──────────────────────────
        corrections = self._reconcile_gstin_pan(extracted)

        # ── Language metadata ──────────────────────────────────────────────────
        meta = extracted.get("_meta") or {}
        detected_language = meta.get("document_language", "Unknown")
        detected_language_code = meta.get("document_language_code", "und")
        is_indian = meta.get("is_indian_document", True)
        was_translated = meta.get("was_translated", False)

        log_audit(
            self.db,
            document_id=document_id,
            entity_type="DOCUMENT",
            action="DATA_EXTRACTED",
            agent=self.name,
            after_state={
                "extracted_fields": list(extracted.keys()),
                "gstin_pan_corrections": corrections,
                "document_language": detected_language,
                "is_indian_document": is_indian,
            },
            stage=ProcessingStage.EXTRACTION,
        )

        # ── Populate Document Fields ───────────────────────────────────────────
        self._populate_document(doc, extracted)

        # ── Save Line Items ────────────────────────────────────────────────────
        self._save_line_items(doc, extracted.get("line_items", []))

        # ── Vendor Lookup ──────────────────────────────────────────────────────
        # GSTIN is the strongest key, but plenty of real vendors (legal/
        # professional services, unregistered small suppliers) have no GST
        # registration at all — PAN, then exact name, are the fallbacks.
        # Without this, every no-GST vendor invoice would post to ERP with an
        # unresolved vendor ("Accounts Payable - UNKNOWN") even though the
        # vendor master record exists.
        vendor_data = extracted.get("vendor") or {}
        vendor = None
        vendor_gstin = vendor_data.get("gstin")
        if vendor_gstin:
            vendor = self.db.query(Vendor).filter(Vendor.gstin == vendor_gstin).first()
        if not vendor and vendor_data.get("pan"):
            vendor = self.db.query(Vendor).filter(Vendor.pan == vendor_data["pan"]).first()
        if not vendor and vendor_data.get("name"):
            vendor = self.db.query(Vendor).filter(
                Vendor.name.ilike(vendor_data["name"].strip())
            ).first()
        if vendor:
            doc.vendor_id = vendor.id

        # ── Save Extracted JSON to File ────────────────────────────────────────
        storage = get_storage()
        extracted_rel = storage.extracted_path(doc.document_id)
        extracted_full = str(Path(settings.UPLOAD_DIR) / extracted_rel)
        Path(extracted_full).parent.mkdir(parents=True, exist_ok=True)
        with open(extracted_full, "w", encoding="utf-8") as f:
            json.dump(extracted, f, indent=2, default=str)

        doc.extracted_path = extracted_full
        doc.extracted_data = extracted
        # Persist the source text used for extraction (digital text layer or OCR output)
        if not doc.ocr_text:
            doc.ocr_text = ocr_text
        self.db.flush()

        update_workflow_stage(
            self.db,
            document_id=document_id,
            stage=ProcessingStage.UNIVERSAL_VALIDATION,
            agent=self.name,
            progress_percent=50,
            stage_details={"fields_extracted": len([k for k, v in self._flatten(extracted).items() if v])},
        )

        state["extracted_data"] = extracted
        state["document_language"] = detected_language
        state["document_language_code"] = detected_language_code
        state["is_indian_document"] = is_indian
        state["was_translated"] = was_translated
        state.set_status("SUCCESS")
        state.set_next_agent("UNIVERSAL_VALIDATION_AGENT")
        return state

    def _populate_document(self, doc: Document, data: Dict[str, Any]) -> None:
        invoice = data.get("invoice") or {}
        amounts = data.get("amounts") or {}
        refs = data.get("references") or {}

        # Invoice fields
        doc.invoice_number = invoice.get("invoice_number")
        if invoice.get("invoice_date"):
            try:
                doc.invoice_date = datetime.strptime(invoice["invoice_date"], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass

        # Amounts
        doc.invoice_amount = self._to_decimal(amounts.get("subtotal"))
        doc.tax_amount = self._to_decimal(amounts.get("total_tax"))
        doc.total_amount = self._to_decimal(amounts.get("total_amount"))
        if invoice.get("currency"):
            doc.currency = invoice["currency"]

        # References — only link the PO if it actually exists in ERP.
        # If the invoice prints a PO number that isn't in our system
        # (wrong number, vendor's own ref, legacy number) clear it from
        # extracted_data so downstream agents don't treat it as a valid
        # ERP reference and skip open-PO resolution.
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
                # PO number printed on invoice not found in ERP — clear it so
                # BusinessProfileAgent runs open-PO resolution instead of
                # treating this as a confirmed PO-backed invoice.
                refs.pop("po_number", None)
                if isinstance(data.get("references"), dict):
                    data["references"].pop("po_number", None)

        if refs.get("grn_number"):
            from app.models.models import GRN
            grn = self.db.query(GRN).filter(GRN.grn_number == refs["grn_number"]).first()
            if grn:
                doc.grn_id = grn.id

        if refs.get("contract_number"):
            from app.models.models import Contract
            contract = self.db.query(Contract).filter(
                Contract.contract_number == refs["contract_number"]
            ).first()
            if contract:
                doc.contract_id = contract.id

        if refs.get("employee_code"):
            from app.models.models import Employee
            emp = self.db.query(Employee).filter(
                Employee.employee_code == refs["employee_code"]
            ).first()
            if emp:
                doc.employee_id = emp.id

    @staticmethod
    def _reconcile_gstin_pan(extracted: Dict[str, Any]) -> List[str]:
        """
        GSTIN characters 3-12 are exactly the PAN. Use whichever is valid to
        correct the other — fixes common OCR/AI digit↔letter mistakes (0/O, 9/g…).
        Returns a list of human-readable corrections made.
        """
        import re
        corrections: List[str] = []
        vendor = extracted.get("vendor") or {}
        gstin = (vendor.get("gstin") or "").strip().upper()
        pan = (vendor.get("pan") or "").strip().upper()

        gstin_re = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
        pan_re = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

        gstin_ok = bool(gstin_re.match(gstin))
        pan_ok = bool(pan_re.match(pan))

        # GSTIN valid but PAN missing/invalid → derive PAN from GSTIN[2:12]
        if gstin_ok and not pan_ok:
            derived = gstin[2:12]
            if pan_re.match(derived):
                vendor["pan"] = derived
                corrections.append(f"PAN set to {derived} (derived from GSTIN)")

        # PAN valid but GSTIN's embedded PAN differs → fix GSTIN's middle segment
        elif pan_ok and len(gstin) == 15 and gstin[2:12] != pan:
            fixed = gstin[:2] + pan + gstin[12:]
            if gstin_re.match(fixed):
                corrections.append(f"GSTIN corrected {gstin} → {fixed} (PAN segment realigned)")
                vendor["gstin"] = fixed

        extracted["vendor"] = vendor
        return corrections

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
                uom=item.get("uom"),
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

    @staticmethod
    def _to_decimal(value: Any) -> Optional[Decimal]:
        if value is None:
            return None
        try:
            cleaned = str(value).replace(",", "").replace(" ", "").strip()
            return Decimal(cleaned)
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _flatten(d: dict, parent_key: str = "") -> dict:
        items = {}
        for k, v in d.items():
            new_key = f"{parent_key}.{k}" if parent_key else k
            if isinstance(v, dict):
                items.update(ExtractionAgent._flatten(v, new_key))
            else:
                items[new_key] = v
        return items
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.agents.base import AgentState, BaseAgent
from app.models.models import (
    Document, DocumentLineItem, ValidationResult, ValidationStatus,
    Vendor, ProcessingStage
)
from app.tools.audit_tool import log_audit, update_workflow_stage

# ISO 639-1 codes considered Indian (GSTIN/PAN/IFSC checks apply)
_INDIAN_LANG_CODES = {
    "en", "hi", "mr", "pa", "gu", "ta", "te", "kn", "ml", "bn", "ur", "or", "as", "sa",
}


def _is_indian_doc(extracted: Dict) -> bool:
    """Return True if the document appears to be from India."""
    meta = extracted.get("_meta") or {}
    # Explicit flag from extraction agent
    if "is_indian_document" in meta:
        return bool(meta["is_indian_document"])
    # Fallback: Indian language code
    lang_code = (meta.get("document_language_code") or "en").lower()
    if lang_code in _INDIAN_LANG_CODES:
        return True
    # Fallback: GSTIN/PAN present → Indian
    vendor = extracted.get("vendor") or {}
    buyer = extracted.get("buyer") or {}
    if vendor.get("gstin") or vendor.get("pan") or buyer.get("gstin"):
        return True
    return False


class UniversalValidationAgent(BaseAgent):
    """
    Agent 5: UNIVERSAL VALIDATION
    Runs on every document before business profile prediction.
    Validates: GST, PAN, duplicates, mandatory fields, arithmetic, dates, bank details.

    For non-Indian documents (Spanish, French, German, Arabic, Chinese, etc.) the
    India-specific checks (GSTIN, PAN, IFSC) are skipped gracefully instead of failing.
    """

    name = "UNIVERSAL_VALIDATION_AGENT"
    progress_on_entry = 50
    progress_on_exit = 60

    def _execute(self, state: AgentState) -> AgentState:
        document_id: str = state["document_id"]
        extracted: Dict[str, Any] = state.get("extracted_data", {}) or {}

        doc = self.db.query(Document).filter(Document.id == document_id).first()
        vendor_data = extracted.get("vendor") or {}
        amounts = extracted.get("amounts") or {}
        invoice = extracted.get("invoice") or {}
        line_items = extracted.get("line_items") or []

        meta = extracted.get("_meta") or {}
        detected_language = meta.get("document_language", "Unknown")
        is_indian = _is_indian_doc(extracted)

        results = []

        # ── Language Detection Rule ────────────────────────────────────────────
        results.append(self._report_language(meta, is_indian))

        # ── 1. Vendor GST Validation (Indian docs only) ───────────────────────
        if is_indian:
            results.append(self._validate_gstin(vendor_data.get("gstin")))
        else:
            results.append(self._skip_indian_check("GSTIN_FORMAT", "GSTIN Format", detected_language))

        # ── 2. PAN Validation (Indian docs only) ─────────────────────────────
        if is_indian:
            results.append(self._validate_pan(vendor_data.get("pan")))
        else:
            results.append(self._skip_indian_check("PAN_FORMAT", "PAN Format", detected_language))

        # ── 3. Mandatory Fields ───────────────────────────────────────────────
        results.extend(self._validate_mandatory_fields(extracted))

        # ── 4. Duplicate Detection ────────────────────────────────────────────
        results.append(self._check_duplicate(doc, vendor_data, invoice))

        # ── 5. Date Validation ────────────────────────────────────────────────
        results.extend(self._validate_dates(invoice))

        # ── 6. Arithmetic Validation ──────────────────────────────────────────
        results.extend(self._validate_arithmetic(amounts, line_items))

        # ── 7. Bank Details Validation ────────────────────────────────────────
        if is_indian:
            results.append(self._validate_bank_details(vendor_data))
        else:
            results.append(self._validate_international_bank(vendor_data))

        # ── 8. Vendor Exists in Master ────────────────────────────────────────
        results.append(self._validate_vendor_master(vendor_data, doc))

        # ── Save Results ──────────────────────────────────────────────────────
        fail_count = 0
        warn_count = 0
        duplicate_detected = False
        for rule_code, rule_name, status, expected, actual, reason, severity in results:
            vr = ValidationResult(
                document_id=document_id,
                rule_code=rule_code,
                rule_name=rule_name,
                status=status,
                expected_value=str(expected) if expected is not None else None,
                actual_value=str(actual) if actual is not None else None,
                reason=reason,
                severity=severity,
                agent=self.name,
            )
            self.db.add(vr)
            if status == ValidationStatus.FAIL:
                fail_count += 1
                if rule_code == "DUPLICATE_INVOICE":
                    duplicate_detected = True
            elif status == ValidationStatus.WARNING:
                warn_count += 1

        self.db.flush()

        log_audit(
            self.db,
            document_id=document_id,
            entity_type="DOCUMENT",
            action="UNIVERSAL_VALIDATION_COMPLETE",
            agent=self.name,
            after_state={
                "total_rules": len(results),
                "fail_count": fail_count,
                "warning_count": warn_count,
                "pass_count": len(results) - fail_count - warn_count,
                "document_language": detected_language,
                "is_indian_document": is_indian,
            },
            stage=ProcessingStage.UNIVERSAL_VALIDATION,
        )

        # ── Duplicate invoice → hard stop to human review ──────────────────────
        if duplicate_detected:
            from app.models.models import (
                DocumentStatus, Exception as Ex,
                ExceptionSeverity, ExceptionQueue, ExceptionStatus,
            )
            from app.core.config import settings
            ex = Ex(
                document_id=document_id,
                exception_code="DUPLICATE_INVOICE",
                exception_type="DUPLICATE_INVOICE",
                severity=ExceptionSeverity.HIGH,
                queue=ExceptionQueue.AP_TEAM,
                title="Duplicate Invoice Detected",
                description="An invoice with the same number already exists in the system. "
                            "This document has been held to prevent double payment.",
                agent_raised_by=self.name,
                status=ExceptionStatus.OPEN,
                sla_hours=settings.SLA_AP_TEAM_HOURS,
            )
            self.db.add(ex)
            doc.status = DocumentStatus.HUMAN_REVIEW_REQUIRED
            self.db.flush()
            update_workflow_stage(
                self.db, document_id=document_id,
                stage=ProcessingStage.EXCEPTION, agent=self.name,
                progress_percent=60, error_message="Duplicate invoice — held for review",
            )
            state.set_status("HUMAN_REVIEW_REQUIRED")
            state.set_next_agent("EXCEPTION_AGENT")
            return state

        update_workflow_stage(
            self.db,
            document_id=document_id,
            stage=ProcessingStage.BUSINESS_PROFILE_PREDICTION,
            agent=self.name,
            progress_percent=60,
        )

        state["universal_validation_fails"] = fail_count
        state["universal_validation_warnings"] = warn_count
        state.set_status("SUCCESS")
        state.set_next_agent("BUSINESS_PROFILE_AGENT")
        return state

    # ── Validation helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _report_language(meta: Dict, is_indian: bool) -> Tuple:
        language = meta.get("document_language", "Unknown")
        lang_code = meta.get("document_language_code", "und")
        was_translated = meta.get("was_translated", False)
        note = " (fields translated to English)" if was_translated else ""
        context = "Indian" if is_indian else "Non-Indian"
        return (
            "DOCUMENT_LANGUAGE",
            "Document Language Detected",
            ValidationStatus.PASS,
            "Any language supported",
            f"{language} [{lang_code}]",
            f"Detected: {language} | {context} document{note}",
            "INFO",
        )

    @staticmethod
    def _skip_indian_check(rule_code: str, rule_name: str, language: str) -> Tuple:
        return (
            rule_code,
            rule_name,
            ValidationStatus.SKIPPED,
            "N/A for non-Indian documents",
            None,
            f"Skipped — document language is '{language}' (non-Indian). GSTIN/PAN/IFSC are India-specific.",
            "INFO",
        )

    def _validate_gstin(self, gstin: Optional[str]) -> Tuple:
        gstin_pattern = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
        if not gstin:
            return ("GSTIN_PRESENT", "GSTIN Present", ValidationStatus.WARNING, "Non-null GSTIN", None, "GSTIN not found in document", "WARNING")
        if not re.match(gstin_pattern, gstin.upper()):
            return ("GSTIN_FORMAT", "GSTIN Format Valid", ValidationStatus.FAIL, "15-char format DDXXXXXDDDDXDZDX", gstin, "GSTIN format invalid", "FAIL")
        return ("GSTIN_FORMAT", "GSTIN Format Valid", ValidationStatus.PASS, gstin_pattern, gstin, "GSTIN format valid", "FAIL")

    def _validate_pan(self, pan: Optional[str]) -> Tuple:
        pan_pattern = r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$"
        if not pan:
            return ("PAN_PRESENT", "PAN Present", ValidationStatus.WARNING, "Non-null PAN", None, "PAN not found in document", "WARNING")
        if not re.match(pan_pattern, pan.upper()):
            return ("PAN_FORMAT", "PAN Format Valid", ValidationStatus.FAIL, "XXXXXDDDDX", pan, "PAN format invalid", "FAIL")
        return ("PAN_FORMAT", "PAN Format Valid", ValidationStatus.PASS, pan_pattern, pan, "PAN format valid", "FAIL")

    def _validate_mandatory_fields(self, extracted: Dict) -> List[Tuple]:
        results = []
        invoice = extracted.get("invoice") or {}
        vendor = extracted.get("vendor") or {}
        amounts = extracted.get("amounts") or {}

        mandatory = [
            ("invoice_number", invoice.get("invoice_number"), "Invoice Number"),
            ("invoice_date", invoice.get("invoice_date"), "Invoice Date"),
            ("vendor_name", vendor.get("name"), "Vendor Name"),
            ("total_amount", amounts.get("total_amount"), "Total Amount"),
        ]
        for field_code, value, field_name in mandatory:
            if not value:
                results.append((f"MANDATORY_{field_code.upper()}", f"{field_name} Present", ValidationStatus.FAIL, "Non-null value", None, f"{field_name} is missing", "FAIL"))
            else:
                results.append((f"MANDATORY_{field_code.upper()}", f"{field_name} Present", ValidationStatus.PASS, "Non-null value", value, f"{field_name} present", "FAIL"))
        return results

    def _check_duplicate(self, doc: Document, vendor_data: Dict, invoice: Dict) -> Tuple:
        invoice_number = invoice.get("invoice_number")
        if not invoice_number:
            return ("DUPLICATE_INVOICE", "Duplicate Invoice Check", ValidationStatus.SKIPPED, "Unique invoice", None, "Cannot check duplicate without invoice number", "FAIL")

        existing = (
            self.db.query(Document)
            .filter(
                Document.invoice_number == invoice_number,
                Document.id != doc.id,
                Document.status.notin_(["REJECTED", "FAILED"]),
            )
            .first()
        )
        if existing:
            return ("DUPLICATE_INVOICE", "Duplicate Invoice Check", ValidationStatus.FAIL, "Unique invoice", invoice_number, f"Duplicate found: {existing.document_id}", "FAIL")
        return ("DUPLICATE_INVOICE", "Duplicate Invoice Check", ValidationStatus.PASS, "Unique invoice", invoice_number, "No duplicate found", "FAIL")

    def _validate_dates(self, invoice: Dict) -> List[Tuple]:
        results = []
        invoice_date_str = invoice.get("invoice_date")
        if invoice_date_str:
            try:
                invoice_date = datetime.strptime(invoice_date_str, "%Y-%m-%d")
                today = datetime.now()
                if invoice_date > today:
                    results.append(("INVOICE_DATE_FUTURE", "Invoice Date Not Future", ValidationStatus.FAIL, f"<= {today.date()}", invoice_date_str, "Invoice date is in the future", "FAIL"))
                elif (today - invoice_date).days > 365:
                    results.append(("INVOICE_DATE_STALE", "Invoice Date Recency", ValidationStatus.WARNING, "Within 1 year", invoice_date_str, "Invoice date is more than 1 year old", "WARNING"))
                else:
                    results.append(("INVOICE_DATE_FUTURE", "Invoice Date Not Future", ValidationStatus.PASS, f"<= {today.date()}", invoice_date_str, "Invoice date is valid", "FAIL"))
            except ValueError:
                results.append(("INVOICE_DATE_FORMAT", "Invoice Date Format", ValidationStatus.FAIL, "YYYY-MM-DD", invoice_date_str, "Invalid date format", "FAIL"))
        return results

    def _validate_arithmetic(self, amounts: Dict, line_items: List[Dict]) -> List[Tuple]:
        results = []
        if not line_items:
            return results

        try:
            calc_subtotal = sum(
                Decimal(str(item.get("total_amount") or 0)) for item in line_items
            )
            claimed_subtotal = Decimal(str(amounts.get("subtotal") or 0))

            if claimed_subtotal > 0:
                diff = abs(calc_subtotal - claimed_subtotal)
                tolerance = claimed_subtotal * Decimal("0.01")
                if diff > tolerance:
                    results.append(("ARITHMETIC_SUBTOTAL", "Subtotal Arithmetic", ValidationStatus.FAIL, str(calc_subtotal), str(claimed_subtotal), f"Line items sum {calc_subtotal} != subtotal {claimed_subtotal}", "FAIL"))
                else:
                    results.append(("ARITHMETIC_SUBTOTAL", "Subtotal Arithmetic", ValidationStatus.PASS, str(calc_subtotal), str(claimed_subtotal), "Subtotal matches line items", "FAIL"))
        except Exception:
            pass

        return results

    def _validate_bank_details(self, vendor_data: Dict) -> Tuple:
        """Indian IFSC format check."""
        bank_ifsc = vendor_data.get("bank_ifsc")
        ifsc_pattern = r"^[A-Z]{4}0[A-Z0-9]{6}$"
        if bank_ifsc and not re.match(ifsc_pattern, bank_ifsc.upper()):
            return ("BANK_IFSC_FORMAT", "Bank IFSC Format", ValidationStatus.WARNING, "XXXXXXXXXXX (11 chars)", bank_ifsc, "IFSC code format invalid", "WARNING")
        return ("BANK_IFSC_FORMAT", "Bank IFSC Format", ValidationStatus.PASS, "XXXXXXXXXXX", bank_ifsc, "Bank details acceptable", "WARNING")

    @staticmethod
    def _validate_international_bank(vendor_data: Dict) -> Tuple:
        """For non-Indian documents, check for IBAN or SWIFT presence."""
        iban = vendor_data.get("bank_iban")
        swift = vendor_data.get("bank_swift")
        account = vendor_data.get("bank_account")
        if iban or swift or account:
            detail = iban or swift or account
            return ("BANK_DETAILS", "Bank Details Present", ValidationStatus.PASS, "Bank details present", detail, "International bank details found", "WARNING")
        return ("BANK_DETAILS", "Bank Details Present", ValidationStatus.WARNING, "Bank details preferred", None, "No bank details found (IBAN/SWIFT/account)", "WARNING")

    def _validate_vendor_master(self, vendor_data: Dict, doc: Document) -> Tuple:
        if doc.vendor_id:
            vendor = self.db.query(Vendor).filter(Vendor.id == doc.vendor_id).first()
            if vendor:
                if not vendor.is_approved:
                    return ("VENDOR_APPROVED", "Vendor Approved", ValidationStatus.FAIL, "Approved=True", "Approved=False", f"Vendor {vendor.name} is not approved", "FAIL")
                return ("VENDOR_APPROVED", "Vendor Approved", ValidationStatus.PASS, "Approved=True", "Approved=True", f"Vendor {vendor.name} is approved", "FAIL")
        return ("VENDOR_MASTER", "Vendor in Master", ValidationStatus.WARNING, "Vendor exists in master", None, "Vendor not found in master data", "WARNING")

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.agents.base import AgentState, BaseAgent
from app.core.config import settings
from app.models.models import Document, BusinessProfile, ProcessingStage
from app.tools.audit_tool import log_audit, update_workflow_stage


VALID_PROFILES = {
    BusinessProfile.PO_RAW_MATERIAL,
    BusinessProfile.NON_PO_RAW_MATERIAL,
    BusinessProfile.PO_CAPEX,
    BusinessProfile.NON_PO_CAPEX,
    BusinessProfile.PO_OPEX,
    BusinessProfile.NON_PO_OPEX,
    BusinessProfile.LEASE_RENT,
    BusinessProfile.EMPLOYEE_REIMBURSEMENT,
    BusinessProfile.PETTY_CASH,
}

def _is_vendor_invoice(extracted: Dict) -> bool:
    """
    A supplier tax invoice: has a seller GSTIN and/or HSN/SAC-coded line items.
    Such a document is RAW_MATERIAL / CAPEX / OPEX — never reimbursement / petty cash.
    """
    vendor = extracted.get("vendor") or {}
    if vendor.get("gstin"):
        return True
    for li in (extracted.get("line_items") or []):
        if li.get("hsn_sac_code"):
            return True
    return False


def _has_reimbursement_signals(extracted: Dict) -> bool:
    """Reimbursement = an EMPLOYEE claim. Never a supplier tax invoice."""
    if _is_vendor_invoice(extracted):
        return False
    emp = extracted.get("employee_reimbursement") or {}
    refs = extracted.get("references") or {}
    if emp.get("employee_name") or emp.get("claim_date") or emp.get("expense_category"):
        return True
    if refs.get("employee_code") or refs.get("employee_name"):
        return True
    text = json.dumps(extracted).lower()
    return any(kw in text for kw in [
        "expense report", "reimbursement", "expense claim", "reimbursed amount",
        "travel expense", "meal allowance", "submitted by", "reporting manager",
    ])


def _has_lease_signals(extracted: Dict) -> bool:
    """Strong lease signals — explicit lease structure, NOT just the word 'rent'."""
    refs = extracted.get("references") or {}
    lease = extracted.get("lease") or {}
    if refs.get("lease_contract_number"):
        return True
    if lease.get("property_address") or lease.get("lease_start") or lease.get("monthly_rent"):
        return True
    text = json.dumps(extracted).lower()
    # Require lease-specific phrasing, not a stray "rent"
    return any(kw in text for kw in ["lease agreement", "monthly rent", "tenancy", "rental agreement", "lease deed"])


def _is_petty_cash(extracted: Dict) -> bool:
    """Petty cash — explicit petty-cash indicator AND small AND no PO AND not a vendor invoice."""
    if _is_vendor_invoice(extracted):
        return False
    amounts = extracted.get("amounts") or {}
    total = float(str(amounts.get("total_amount") or 0).replace(",", "") or 0)
    petty = extracted.get("petty_cash") or {}
    refs = extracted.get("references") or {}
    text = json.dumps(extracted).lower()
    has_petty_marker = bool(petty.get("petty_cash_holder")) or "petty cash" in text
    return has_petty_marker and total < 5000 and not refs.get("po_number")


# Rules engine — only STRONG, specific signals override the AI. Order = priority.
RULES = [
    # (condition_fn, forced_profile, confidence, reason)
    (lambda d, e: bool((e.get("references") or {}).get("po_number")) and not _has_reimbursement_signals(e) and not _has_lease_signals(e),
     None, 0.0, "Has PO number — defer to AI for PO_* sub-type"),  # sentinel: do NOT override, let AI decide PO type

    (lambda d, e: _has_lease_signals(e) and not (e.get("references") or {}).get("po_number"),
     BusinessProfile.LEASE_RENT, 0.92, "Explicit lease/rent agreement structure detected"),

    (lambda d, e: (_has_reimbursement_signals(e) or bool(d.employee_id)) and not (e.get("references") or {}).get("po_number"),
     BusinessProfile.EMPLOYEE_REIMBURSEMENT, 0.90, "Employee expense-report structure detected"),

    (lambda d, e: _is_petty_cash(e),
     BusinessProfile.PETTY_CASH, 0.88, "Petty cash marker with small amount and no PO"),
]


class BusinessProfileAgent(BaseAgent):
    """
    Agent 6: BUSINESS PROFILE PREDICTION
    AI predicts, Rules validate/override.
    Never asks user. Always determines profile automatically.
    """

    name = "BUSINESS_PROFILE_AGENT"
    progress_on_entry = 60
    progress_on_exit = 70

    def _execute(self, state: AgentState) -> AgentState:
        document_id: str = state["document_id"]
        extracted: Dict[str, Any] = state.get("extracted_data", {}) or {}
        ocr_text: str = state.get("ocr_text", "")

        doc = self.db.query(Document).filter(Document.id == document_id).first()

        # ── Rules Engine Check First ───────────────────────────────────────────
        rules_profile = None
        rules_confidence = 0.0
        rules_reason = ""
        defer_to_ai = False

        for condition_fn, profile, confidence, reason in RULES:
            try:
                if condition_fn(doc, extracted):
                    if profile is None:
                        # Sentinel: a strong signal says "let the AI pick the sub-type"
                        defer_to_ai = True
                        rules_reason = reason
                        break
                    rules_profile = profile
                    rules_confidence = confidence
                    rules_reason = reason
                    break
            except Exception:
                continue

        # ── AI Prediction ──────────────────────────────────────────────────────
        prompt = self.load_prompt("business_profile")
        # Use replace (not .format) — the template contains literal JSON braces
        user_prompt = (
            prompt["user_prompt_template"]
            .replace("{extracted_data}", json.dumps(extracted, indent=2, default=str)[:3000])
            .replace("{ocr_text_snippet}", ocr_text[:2000])
        )

        ai_result = self._call_openai_json(
            system_prompt=prompt["system_prompt"],
            user_prompt=user_prompt,
            model=prompt["model"],
        )

        ai_profile = ai_result.get("profile", "").upper()
        ai_confidence = float(ai_result.get("confidence", 0.0))
        ai_reasoning = ai_result.get("reasoning", "")

        # ── Reconcile Rules vs AI ──────────────────────────────────────────────
        if rules_profile and rules_confidence >= ai_confidence:
            final_profile = rules_profile
            final_confidence = rules_confidence
            final_reason = f"[RULES OVERRIDE] {rules_reason}. AI suggested: {ai_profile} ({ai_confidence:.0%})"
        elif ai_profile in VALID_PROFILES:
            final_profile = ai_profile
            final_confidence = ai_confidence
            final_reason = f"[AI] {ai_reasoning}"
        else:
            # AI returned invalid profile — fallback rules
            final_profile = self._heuristic_fallback(extracted, doc)
            final_confidence = 0.6
            final_reason = f"[HEURISTIC] AI returned invalid profile '{ai_profile}'. Applied heuristic fallback."

        # ── Enterprise PO determination ────────────────────────────────────────
        # The printed PO number is only one signal. If the vendor is PO-mandatory
        # OR an open blanket PO covers these items, the invoice is PO-backed even
        # when no PO number is printed.
        refs = extracted.get("references") or {}
        is_goods_or_service = final_profile in {
            BusinessProfile.NON_PO_RAW_MATERIAL, BusinessProfile.PO_RAW_MATERIAL,
            BusinessProfile.NON_PO_CAPEX, BusinessProfile.PO_CAPEX,
            BusinessProfile.NON_PO_OPEX, BusinessProfile.PO_OPEX,
        }
        if is_goods_or_service and not doc.po_id:
            po_backed, po_reason, resolved_po = self._check_po_backed(doc)
            if po_backed:
                # Promote NON_PO_* → PO_* (keep the goods/capex/opex category)
                promoted = final_profile.replace("NON_PO_", "PO_")
                if promoted in VALID_PROFILES:
                    final_profile = promoted
                    final_reason += f" | [PO RESOLUTION] {po_reason}"
                    # Attach the PO now — ProfileValidationAgent (which runs before
                    # MatchingAgent) checks doc.po_id to validate PO_* profiles, so
                    # without this it would fail PO_MANDATORY even though a real
                    # open PO governs this invoice. MatchingAgent re-resolves and
                    # confirms/draws-down against the same PO afterwards.
                    if resolved_po is not None and not doc.po_id:
                        doc.po_id = resolved_po.id
                        if not doc.vendor_id:
                            doc.vendor_id = resolved_po.vendor_id
                        self.db.flush()

        # ── Enterprise GRN resolution ───────────────────────────────────────────
        # A vendor invoice virtually never prints the buyer's internal GRN
        # number — it's raised by the warehouse on receipt, after the invoice
        # exists. Whenever a PO is governing this invoice (printed or resolved
        # above), look up the matching accepted GRN the same way an AP clerk
        # would: by PO + vendor. Without this, GRN_MANDATORY would fail on
        # every real-world PO invoice even though goods were received.
        if doc.po_id and not doc.grn_id:
            from app.models.models import PurchaseOrder
            from app.services.po_matching import find_governing_grn
            po = self.db.query(PurchaseOrder).filter(PurchaseOrder.id == doc.po_id).first()
            if po:
                grn_resolution = find_governing_grn(self.db, doc, po)
                if grn_resolution.grn is not None:
                    doc.grn_id = grn_resolution.grn.id
                    final_reason += f" | [GRN RESOLUTION] {grn_resolution.reason}"
                    self.db.flush()

        log_audit(
            self.db,
            document_id=document_id,
            entity_type="DOCUMENT",
            action="BUSINESS_PROFILE_PREDICTED",
            agent=self.name,
            after_state={
                "ai_profile": ai_profile,
                "ai_confidence": ai_confidence,
                "rules_profile": rules_profile,
                "final_profile": final_profile,
                "final_confidence": final_confidence,
            },
            stage=ProcessingStage.BUSINESS_PROFILE_PREDICTION,
        )

        doc.business_profile = final_profile
        doc.ai_profile_confidence = final_confidence
        doc.ai_profile_reasoning = final_reason
        self.db.flush()

        update_workflow_stage(
            self.db,
            document_id=document_id,
            stage=ProcessingStage.PROFILE_VALIDATION,
            agent=self.name,
            progress_percent=70,
        )

        state["business_profile"] = final_profile
        state["profile_confidence"] = final_confidence
        state["profile_reasoning"] = final_reason
        state.set_status("SUCCESS")
        state.set_next_agent("PROFILE_VALIDATION_AGENT")
        return state

    def _check_po_backed(self, doc: Document) -> tuple[bool, str, Optional["PurchaseOrder"]]:
        """
        A no-PO-number invoice is still PO-backed when:
          1. The vendor is explicitly PO-mandatory (po_required), or
          2. An open PO for this vendor actually covers the invoiced items
             (same resolution MatchingAgent uses — vendor + line-item match +
             remaining balance). This is what lets ERP-seeded blanket/standing
             POs auto-attach even when the invoice itself never prints a PO
             number (e.g. the Dotpe / Ace One / 3MB / A.D. Corp sample invoices).
        We do NOT fabricate a PO for vendors with no matching open PO at all —
        those correctly stay NON-PO.

        Returns (is_po_backed, reason, resolved_po_or_None).
        """
        from app.models.models import DocumentLineItem, Vendor

        from app.services.po_matching import find_governing_po
        invoice_lines = self.db.query(DocumentLineItem).filter(
            DocumentLineItem.document_id == doc.id
        ).all()
        resolution = find_governing_po(self.db, doc, invoice_lines)
        if resolution.po is not None:
            return True, resolution.reason, resolution.po

        if doc.vendor_id:
            vendor = self.db.query(Vendor).filter(Vendor.id == doc.vendor_id).first()
            if vendor and vendor.po_required:
                return True, f"Vendor '{vendor.name}' is PO-mandatory (po_required)", None

        return False, "No PO number on invoice, vendor is not PO-mandatory, and no open PO covers these items → NON-PO", None

    @staticmethod
    def _heuristic_fallback(extracted: Dict, doc: Document) -> str:
        refs = extracted.get("references") or {}
        amounts = extracted.get("amounts") or {}
        total = float(str(amounts.get("total_amount") or 0).replace(",", "") or 0)

        if doc.employee_id:
            return BusinessProfile.EMPLOYEE_REIMBURSEMENT
        if refs.get("lease_contract_number"):
            return BusinessProfile.LEASE_RENT
        if refs.get("po_number"):
            return BusinessProfile.PO_OPEX
        if total < 5000:
            return BusinessProfile.PETTY_CASH
        return BusinessProfile.NON_PO_OPEX
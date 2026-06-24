from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.agents.base import AgentState, BaseAgent
from app.core.config import settings
from app.models.models import (
    Document, DocumentLineItem, GRN, GRNLineItem, MatchingResult,
    MatchStatus, POLineItem, ProcessingStage, PurchaseOrder
)
from app.tools.audit_tool import log_audit, update_workflow_stage


class MatchingAgent(BaseAgent):
    """
    Agent 8: PO/GRN MATCHING
    Runs only for PO-backed profiles.
    Performs 3-way matching: Invoice vs PO vs GRN.
    Tolerance rules from config (DB overrides in future).
    """

    name = "MATCHING_AGENT"
    progress_on_entry = 78
    progress_on_exit = 85

    def _execute(self, state: AgentState) -> AgentState:
        document_id: str = state["document_id"]

        doc = self.db.query(Document).filter(Document.id == document_id).first()

        invoice_lines = self.db.query(DocumentLineItem).filter(
            DocumentLineItem.document_id == document_id
        ).all()

        # ── Resolve the governing PO (printed PO, or open blanket PO by items) ──
        from app.services.po_matching import find_governing_po, apply_drawdown
        resolution = find_governing_po(self.db, doc, invoice_lines)
        if resolution.po is None:
            return self._no_po_found(state, doc, document_id)

        po = resolution.po
        doc.po_id = po.id
        self.db.flush()
        grn = self.db.query(GRN).filter(GRN.id == doc.grn_id).first() if doc.grn_id else None

        # ── 3-Way Match ────────────────────────────────────────────────────────
        match_result = self._perform_matching(doc, po, grn, invoice_lines)

        # ── Cumulative draw-down (one blanket PO across many invoices) ──────────
        drawdown = apply_drawdown(self.db, po, invoice_lines)
        match_result["variance_report"]["drawdown"] = drawdown
        match_result["variance_report"]["po_resolution"] = resolution.method
        if drawdown.get("over_billing"):
            match_result["status"] = MatchStatus.MISMATCH
            match_result["notes"] += " | OVER-BILLING: invoice qty exceeds remaining PO balance"

        # Save result
        mr = MatchingResult(
            document_id=document_id,
            po_id=po.id,
            grn_id=grn.id if grn else None,
            match_status=match_result["status"],
            overall_match_score=match_result["score"],
            quantity_match=match_result["quantity_match"],
            price_match=match_result["price_match"],
            tax_match=match_result["tax_match"],
            total_match=match_result["total_match"],
            vendor_match=match_result["vendor_match"],
            variance_report=match_result["variance_report"],
            line_matches=match_result["line_matches"],
            tolerance_applied=match_result["tolerance_applied"],
            matching_notes=match_result["notes"],
        )
        self.db.add(mr)
        self.db.flush()

        log_audit(
            self.db,
            document_id=document_id,
            entity_type="MATCHING",
            entity_id=str(mr.id),
            action="MATCHING_COMPLETE",
            agent=self.name,
            after_state={"status": match_result["status"], "score": float(match_result["score"])},
            stage=ProcessingStage.MATCHING,
        )

        if match_result["status"] == MatchStatus.MISMATCH:
            self._create_matching_exception(doc, match_result)

        update_workflow_stage(
            self.db, document_id=document_id,
            stage=ProcessingStage.APPROVAL,
            agent=self.name, progress_percent=85,
        )

        state["matching_status"] = match_result["status"]
        state["matching_score"] = float(match_result["score"])
        state.set_status("SUCCESS")
        state.set_next_agent("APPROVAL_AGENT")
        return state

    def _perform_matching(
        self, doc: Document, po: PurchaseOrder, grn: Optional[GRN], invoice_lines: List[DocumentLineItem]
    ) -> Dict[str, Any]:
        price_tol = Decimal(str(settings.PRICE_TOLERANCE_PERCENT)) / 100
        qty_tol = Decimal(str(settings.QUANTITY_TOLERANCE_PERCENT)) / 100

        # Vendor match
        vendor_match = (str(doc.vendor_id) == str(po.vendor_id)) if doc.vendor_id and po.vendor_id else False

        from app.services.po_matching import line_matches as _content_line_matches
        po_lines_all = self.db.query(POLineItem).filter(POLineItem.po_id == po.id).all()
        used_po_line_ids: set = set()

        line_matches = []
        total_quantity_ok = True
        total_price_ok = True
        tolerance_applied = False

        for inv_line in invoice_lines:
            # Pair by actual content (item code / HSN / description overlap) —
            # line_number rarely lines up between an invoice and its PO, and
            # blindly grabbing "the first PO line" produced nonsense pairings
            # (e.g. an "Installation charges" line compared against a POS
            # terminal's price/qty). Prefer a PO line not already claimed by
            # an earlier invoice line; a single-line PO (lump-sum / blanket
            # supply) is the one sane exception — every invoice line governs it.
            candidates = [pl for pl in po_lines_all if _content_line_matches(inv_line, pl)]
            unused_candidates = [pl for pl in candidates if pl.id not in used_po_line_ids]
            if unused_candidates:
                po_line = unused_candidates[0]
            elif candidates:
                po_line = candidates[0]
            elif len(po_lines_all) == 1:
                po_line = po_lines_all[0]
            else:
                po_line = None

            if po_line:
                used_po_line_ids.add(po_line.id)

            if not po_line:
                line_matches.append({
                    "line_number": inv_line.line_number,
                    "status": "NO_PO_LINE",
                    "invoice": {"qty": float(inv_line.quantity or 0), "price": float(inv_line.unit_price or 0)},
                    "po": None,
                    "grn": None,
                })
                continue

            # Quantity check
            inv_qty = Decimal(str(inv_line.quantity or 0))
            po_qty = Decimal(str(po_line.quantity or 0))
            grn_qty = Decimal("0")

            if grn:
                grn_line = self.db.query(GRNLineItem).filter(
                    GRNLineItem.grn_id == grn.id,
                    GRNLineItem.po_line_id == po_line.id,
                ).first()
                if grn_line:
                    grn_qty = Decimal(str(grn_line.accepted_quantity or 0))

            effective_qty = grn_qty if grn_qty > 0 else po_qty
            qty_ok = self._within_tolerance(inv_qty, effective_qty, qty_tol)
            if not qty_ok and self._within_tolerance(inv_qty, effective_qty, Decimal("0.05")):
                qty_ok = True
                tolerance_applied = True
            if not qty_ok:
                total_quantity_ok = False

            # Price check
            inv_price = Decimal(str(inv_line.unit_price or 0))
            po_price = Decimal(str(po_line.unit_price or 0))
            price_ok = self._within_tolerance(inv_price, po_price, price_tol)
            if price_ok and price_tol > 0:
                tolerance_applied = True
            if not price_ok:
                total_price_ok = False

            # Link invoice line to PO line
            inv_line.po_line_id = po_line.id

            line_matches.append({
                "line_number": inv_line.line_number,
                "item": inv_line.description or po_line.description or "—",
                "status": "MATCH" if (qty_ok and price_ok) else "MISMATCH",
                "invoice": {"qty": float(inv_qty), "price": float(inv_price)},
                "po": {"qty": float(po_qty), "price": float(po_price)},
                "grn": {"qty": float(grn_qty)} if grn else None,
                "qty_ok": qty_ok,
                "price_ok": price_ok,
            })

        self.db.flush()

        # Total amount match
        inv_total = Decimal(str(doc.total_amount or 0))
        po_total = Decimal(str(po.total_amount or 0))
        total_ok = self._within_tolerance(inv_total, po_total, price_tol)
        tax_ok = True  # Simplified — full tax cross-check can be added

        # Score
        checks = [vendor_match, total_quantity_ok, total_price_ok, tax_ok, total_ok]
        score = Decimal(str(sum(checks) / len(checks)))

        if all(checks):
            status = MatchStatus.MATCHED
        elif tolerance_applied and score >= Decimal("0.8"):
            status = MatchStatus.TOLERANCE_MATCH
        elif score >= Decimal("0.5"):
            status = MatchStatus.PARTIAL_MATCH
        else:
            status = MatchStatus.MISMATCH

        return {
            "status": status,
            "score": score,
            "vendor_match": vendor_match,
            "quantity_match": total_quantity_ok,
            "price_match": total_price_ok,
            "tax_match": tax_ok,
            "total_match": total_ok,
            "tolerance_applied": tolerance_applied,
            "line_matches": line_matches,
            "variance_report": {
                "invoice_total": float(inv_total),
                "po_total": float(po_total),
                "total_variance": float(abs(inv_total - po_total)),
                "total_variance_pct": float(abs(inv_total - po_total) / po_total * 100) if po_total else 0,
            },
            "notes": f"3-way match: {status}. Score: {score:.0%}. Lines matched: {sum(1 for l in line_matches if l.get('status') == 'MATCH')}/{len(line_matches)}",
        }

    @staticmethod
    def _within_tolerance(value: Decimal, reference: Decimal, tolerance: Decimal) -> bool:
        if reference == 0:
            return value == 0
        variance = abs(value - reference) / reference
        return variance <= tolerance

    def _no_po_found(self, state: AgentState, doc: Document, document_id: str) -> AgentState:
        mr = MatchingResult(
            document_id=document_id,
            match_status=MatchStatus.NOT_APPLICABLE,
            overall_match_score=Decimal("0"),
            matching_notes="No PO found for matching",
        )
        self.db.add(mr)
        self.db.flush()

        from app.models.models import Exception as Ex, ExceptionSeverity, ExceptionQueue, ExceptionStatus
        ex = Ex(
            document_id=document_id,
            exception_code="PO_NOT_FOUND",
            exception_type="MATCHING_FAILURE",
            severity=ExceptionSeverity.HIGH,
            queue=ExceptionQueue.PROCUREMENT,
            title="PO Not Found for Matching",
            description="Document requires PO matching but no PO was found or linked",
            agent_raised_by=self.name,
            status=ExceptionStatus.OPEN,
            sla_hours=settings.SLA_PROCUREMENT_HOURS,
        )
        self.db.add(ex)
        self.db.flush()

        update_workflow_stage(
            self.db, document_id=document_id,
            stage=ProcessingStage.APPROVAL,
            agent=self.name, progress_percent=85,
        )
        state.set_status("SUCCESS")
        state.set_next_agent("APPROVAL_AGENT")
        return state

    def _create_matching_exception(self, doc: Document, match_result: Dict) -> None:
        from app.models.models import Exception as Ex, ExceptionSeverity, ExceptionQueue, ExceptionStatus
        ex = Ex(
            document_id=doc.id,
            exception_code="MATCHING_MISMATCH",
            exception_type="MATCHING_FAILURE",
            severity=ExceptionSeverity.HIGH,
            queue=ExceptionQueue.PROCUREMENT,
            title="Invoice does not match PO/GRN",
            description=match_result.get("notes", ""),
            agent_raised_by=self.name,
            status=ExceptionStatus.OPEN,
            sla_hours=settings.SLA_PROCUREMENT_HOURS,
        )
        self.db.add(ex)
        self.db.flush()
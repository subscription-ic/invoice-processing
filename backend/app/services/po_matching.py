"""
Enterprise PO resolution & draw-down logic.

Handles the real-world case where ONE blanket/standing PO covers MANY invoices,
and where an invoice may not print its PO number at all.

Resolution hierarchy (strongest → weakest):
  1. Explicit PO number on the invoice (already linked as doc.po_id)
  2. Open-PO lookup by vendor + line-item match + remaining balance
  3. Vendor flagged po_required but no PO found  → caller raises an exception

Draw-down: each invoice consumes part of the PO's remaining quantity/amount.
Cumulative invoiced quantity can never exceed the PO line quantity (over-billing guard).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.models import (
    Document, DocumentLineItem, GRN, GRNStatus, POStatus, PurchaseOrder, POLineItem,
)


@dataclass
class POResolution:
    po: Optional[PurchaseOrder]
    method: str          # "PRINTED" | "OPEN_PO_LOOKUP" | "NONE"
    reason: str


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def line_matches(inv_line: DocumentLineItem, po_line: POLineItem) -> bool:
    """Match an invoice line to a PO line by item code, HSN, or description overlap.

    Public — reused by MatchingAgent for line-level 3-way scoring so it pairs
    lines by actual content instead of a fragile/meaningless line_number or
    "just take the first PO line" fallback.

    Blanket/open PO lines (no item_code, no HSN — e.g. "Food & consumables —
    blanket supply") are accepted for any invoice line from that vendor because
    they are intentionally generic standing orders.
    """
    if inv_line.item_code and po_line.item_code and _norm(inv_line.item_code) == _norm(po_line.item_code):
        return True
    if inv_line.hsn_sac_code and po_line.hsn_sac_code and inv_line.hsn_sac_code == po_line.hsn_sac_code:
        return True
    di, dp = _norm(inv_line.description), _norm(po_line.description)
    if di and dp and (di in dp or dp in di or _word_overlap(di, dp) >= 0.5):
        return True
    # Blanket PO line: no item_code and no HSN means it's a standing/open order
    # that covers any delivery from this vendor — always matches.
    if not po_line.item_code and not po_line.hsn_sac_code:
        return True
    return False


# Backward-compatible alias for in-module callers.
_line_matches = line_matches


def _word_overlap(a: str, b: str) -> float:
    wa, wb = set(a.split()), set(b.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def _po_remaining_qty(db: Session, po_line: POLineItem) -> Decimal:
    invoiced = Decimal(str(po_line.invoiced_quantity or 0))
    return Decimal(str(po_line.quantity or 0)) - invoiced


def find_governing_po(
    db: Session, doc: Document, invoice_lines: List[DocumentLineItem]
) -> POResolution:
    """Resolve which PO governs this invoice, even when the PO number isn't printed."""
    # 1. Explicit PO already linked (printed on invoice)
    if doc.po_id:
        po = db.query(PurchaseOrder).filter(PurchaseOrder.id == doc.po_id).first()
        if po:
            return POResolution(po, "PRINTED", f"PO {po.po_number} referenced on invoice")

    # 2. Open-PO lookup by vendor + item match + remaining balance
    if doc.vendor_id:
        open_pos = (
            db.query(PurchaseOrder)
            .filter(
                PurchaseOrder.vendor_id == doc.vendor_id,
                PurchaseOrder.status.in_([POStatus.OPEN, POStatus.PARTIALLY_RECEIVED]),
            )
            .order_by(PurchaseOrder.po_date.asc())  # oldest open PO first (FIFO draw-down)
            .all()
        )
        for po in open_pos:
            po_lines = db.query(POLineItem).filter(POLineItem.po_id == po.id).all()
            matched_any = False
            has_balance = False
            for inv_line in invoice_lines:
                for po_line in po_lines:
                    if _line_matches(inv_line, po_line):
                        matched_any = True
                        if _po_remaining_qty(db, po_line) > 0:
                            has_balance = True
                        break
            if matched_any and has_balance:
                return POResolution(
                    po, "OPEN_PO_LOOKUP",
                    f"Linked to open blanket PO {po.po_number} by item match (vendor + remaining balance)",
                )

    return POResolution(None, "NONE", "No governing PO found for this vendor/items")


@dataclass
class GRNResolution:
    grn: Optional[GRN]
    reason: str


def find_governing_grn(db: Session, doc: Document, po: PurchaseOrder) -> GRNResolution:
    """
    Resolve which GRN governs this invoice. A vendor invoice almost never
    prints the buyer's internal GRN number (the GRN is raised by the buyer's
    warehouse on receipt, after the invoice exists) — so the GRN must be
    looked up by PO + vendor, the same way an AP clerk would in the real ERP.
    """
    if doc.grn_id:
        grn = db.query(GRN).filter(GRN.id == doc.grn_id).first()
        if grn:
            return GRNResolution(grn, f"GRN {grn.grn_number} explicitly referenced on invoice")

    candidates = (
        db.query(GRN)
        .filter(GRN.po_id == po.id, GRN.status == GRNStatus.ACCEPTED)
        .order_by(GRN.received_date.asc())
        .all()
    )
    if not candidates:
        return GRNResolution(None, f"No accepted GRN found against PO {po.po_number}")

    # Prefer the GRN raised against the same vendor entity (handles blanket
    # POs shared across multiple vendor/state registrations).
    if doc.vendor_id:
        same_vendor = [g for g in candidates if str(g.vendor_id) == str(doc.vendor_id)]
        if same_vendor:
            g = same_vendor[0]
            return GRNResolution(g, f"GRN {g.grn_number} matched by PO {po.po_number} + vendor")

    g = candidates[0]
    return GRNResolution(g, f"GRN {g.grn_number} matched by PO {po.po_number} (single GRN on file)")


def apply_drawdown(
    db: Session, po: PurchaseOrder, invoice_lines: List[DocumentLineItem]
) -> dict:
    """
    Consume the PO balance for this invoice. Returns a draw-down report and
    flags over-billing (invoice qty exceeds remaining PO qty).
    """
    report = {"lines": [], "over_billing": False, "po_number": po.po_number}
    po_lines = db.query(POLineItem).filter(POLineItem.po_id == po.id).all()

    for inv_line in invoice_lines:
        match = next((pl for pl in po_lines if _line_matches(inv_line, pl)), None)
        if not match:
            report["lines"].append({
                "invoice_desc": inv_line.description, "status": "NO_PO_LINE",
            })
            continue

        inv_qty = Decimal(str(inv_line.quantity or 0))
        remaining = _po_remaining_qty(db, match)
        over = inv_qty > remaining

        # Draw down (cap at remaining to never exceed PO qty)
        consumed = inv_qty if not over else remaining
        match.invoiced_quantity = Decimal(str(match.invoiced_quantity or 0)) + consumed
        # Link the invoice line to the PO line
        inv_line.po_line_id = match.id

        if over:
            report["over_billing"] = True

        report["lines"].append({
            "invoice_desc": inv_line.description,
            "po_line": match.description,
            "invoice_qty": float(inv_qty),
            "po_qty": float(match.quantity or 0),
            "remaining_before": float(remaining),
            "consumed": float(consumed),
            "remaining_after": float(_po_remaining_qty(db, match)),
            "over_billing": over,
        })

    # Update PO invoiced_amount + status
    inv_total = Decimal(str(sum(Decimal(str(l.total_amount or 0)) for l in invoice_lines)))
    po.invoiced_amount = Decimal(str(po.invoiced_amount or 0)) + inv_total

    # Recompute status: fully invoiced if every line exhausted
    all_exhausted = all(_po_remaining_qty(db, pl) <= 0 for pl in po_lines) if po_lines else False
    if all_exhausted:
        po.status = POStatus.INVOICED
    elif Decimal(str(po.invoiced_amount or 0)) > 0:
        po.status = POStatus.PARTIALLY_RECEIVED

    db.flush()
    report["po_invoiced_amount"] = float(po.invoiced_amount or 0)
    report["po_total_amount"] = float(po.total_amount or 0)
    report["po_status"] = po.status
    return report
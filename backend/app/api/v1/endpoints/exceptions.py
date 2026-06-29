from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_async_session
from app.core.security import get_current_user
from app.models.models import (
    Document, Exception as Ex, ExceptionStatus, MatchingResult,
    User, ValidationResult,
)
from app.schemas.schemas import ExceptionAssign, ExceptionOut, ExceptionResolve

router = APIRouter(prefix="/exceptions", tags=["Exceptions"])


@router.get("", response_model=List[ExceptionOut])
async def list_exceptions(
    queue: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    document_id: Optional[str] = Query(None),
    assigned_to_me: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    q = select(Ex)
    if queue:
        q = q.where(Ex.queue == queue)
    if status:
        q = q.where(Ex.status == status)
    if severity:
        q = q.where(Ex.severity == severity)
    if document_id:
        q = q.where(Ex.document_id == document_id)
    if assigned_to_me:
        q = q.where(Ex.assigned_to == str(current_user.id))
    q = q.order_by(desc(Ex.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    exceptions = result.scalars().all()
    return [_map_exception(e) for e in exceptions]


@router.get("/{exception_id}", response_model=ExceptionOut)
async def get_exception(
    exception_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Ex).where(Ex.id == exception_id))
    ex = result.scalar_one_or_none()
    if not ex:
        raise HTTPException(status_code=404, detail="Exception not found")
    return _map_exception(ex)


@router.get("/{exception_id}/summary")
async def get_exception_summary(
    exception_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Rich exception summary: exception detail + document snapshot + type-specific
    context (duplicate comparison, match variance, validation failures, etc.).
    This is what the Exception Detail page shows — no redirect to the document page.
    """
    # ── Exception ────────────────────────────────────────────────────────────
    ex_result = await db.execute(select(Ex).where(Ex.id == exception_id))
    ex = ex_result.scalar_one_or_none()
    if not ex:
        raise HTTPException(status_code=404, detail="Exception not found")

    # ── Document (with vendor eager-loaded) ───────────────────────────────
    doc_result = await db.execute(
        select(Document)
        .options(selectinload(Document.vendor))
        .where(Document.id == ex.document_id)
    )
    doc = doc_result.scalar_one_or_none()

    def _doc_snapshot(d: Document) -> Dict[str, Any]:
        vendor_name = (
            (d.vendor.name if d.vendor else None)
            or ((d.extracted_data or {}).get("vendor", {}) or {}).get("name")
        )
        return {
            "id": str(d.id),
            "document_id": d.document_id,
            "original_filename": d.original_filename,
            "status": d.status,
            "vendor_name": vendor_name,
            "vendor_gstin": ((d.extracted_data or {}).get("vendor", {}) or {}).get("gstin"),
            "invoice_number": d.invoice_number,
            "invoice_date": d.invoice_date.isoformat() if d.invoice_date else None,
            "total_amount": float(d.total_amount) if d.total_amount else None,
            "invoice_amount": float(d.invoice_amount) if d.invoice_amount else None,
            "tax_amount": float(d.tax_amount) if d.tax_amount else None,
            "currency": d.currency or "INR",
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }

    document_snapshot = _doc_snapshot(doc) if doc else None

    # ── Validation failures for this document ────────────────────────────
    vr_result = await db.execute(
        select(ValidationResult)
        .where(
            ValidationResult.document_id == ex.document_id,
            ValidationResult.status == "FAIL",
        )
        .order_by(ValidationResult.created_at)
    )
    validation_failures = [
        {
            "rule_code": v.rule_code,
            "rule_name": v.rule_name,
            "status": v.status,
            "expected_value": v.expected_value,
            "actual_value": v.actual_value,
            "reason": v.reason,
            "severity": v.severity,
        }
        for v in vr_result.scalars().all()
    ]

    # ── Matching result (if any) ──────────────────────────────────────────
    mr_result = await db.execute(
        select(MatchingResult).where(MatchingResult.document_id == ex.document_id)
    )
    mr = mr_result.scalar_one_or_none()
    matching_detail: Optional[Dict[str, Any]] = None
    if mr:
        matching_detail = {
            "match_status": mr.match_status,
            "overall_match_score": float(mr.overall_match_score or 0),
            "quantity_match": mr.quantity_match,
            "price_match": mr.price_match,
            "tax_match": mr.tax_match,
            "total_match": mr.total_match,
            "vendor_match": mr.vendor_match,
            "variance_report": mr.variance_report or {},
            "line_matches": mr.line_matches or [],
            "tolerance_applied": mr.tolerance_applied,
            "matching_notes": mr.matching_notes,
        }

    # ── Duplicate comparison (DUPLICATE_INVOICE only) ─────────────────────
    duplicate_comparison: Optional[Dict[str, Any]] = None
    if ex.exception_code == "DUPLICATE_INVOICE" and doc and doc.invoice_number:
        dup_result = await db.execute(
            select(Document)
            .options(selectinload(Document.vendor))
            .where(
                Document.invoice_number == doc.invoice_number,
                Document.id != doc.id,
                Document.status.notin_(["REJECTED", "FAILED"]),
            )
            .order_by(Document.created_at.desc())
            .limit(1)
        )
        existing = dup_result.scalar_one_or_none()
        if existing:
            duplicate_comparison = {
                "new_invoice": _doc_snapshot(doc),
                "existing_invoice": _doc_snapshot(existing),
                "fields_compared": [
                    {
                        "field": "Invoice Number",
                        "new_value": doc.invoice_number,
                        "existing_value": existing.invoice_number,
                        "match": doc.invoice_number == existing.invoice_number,
                    },
                    {
                        "field": "Total Amount",
                        "new_value": str(doc.total_amount) if doc.total_amount else "—",
                        "existing_value": str(existing.total_amount) if existing.total_amount else "—",
                        "match": doc.total_amount == existing.total_amount,
                    },
                    {
                        "field": "Invoice Date",
                        "new_value": doc.invoice_date.isoformat() if doc.invoice_date else "—",
                        "existing_value": existing.invoice_date.isoformat() if existing.invoice_date else "—",
                        "match": doc.invoice_date == existing.invoice_date,
                    },
                    {
                        "field": "Vendor",
                        "new_value": (
                            (doc.vendor.name if doc.vendor else None)
                            or ((doc.extracted_data or {}).get("vendor", {}) or {}).get("name")
                            or "—"
                        ),
                        "existing_value": (
                            (existing.vendor.name if existing.vendor else None)
                            or ((existing.extracted_data or {}).get("vendor", {}) or {}).get("name")
                            or "—"
                        ),
                        "match": None,
                    },
                    {
                        "field": "Document Status",
                        "new_value": doc.status,
                        "existing_value": existing.status,
                        "match": None,
                    },
                    {
                        "field": "Uploaded Date",
                        "new_value": doc.created_at.strftime("%d %b %Y, %I:%M %p") if doc.created_at else "—",
                        "existing_value": existing.created_at.strftime("%d %b %Y, %I:%M %p") if existing.created_at else "—",
                        "match": None,
                    },
                ],
            }

    # ── Build human-readable "what went wrong" lines ──────────────────────
    what_failed: List[Dict[str, Any]] = []
    code = ex.exception_code

    if code == "DUPLICATE_INVOICE":
        what_failed.append({
            "icon": "duplicate",
            "heading": "Duplicate invoice number",
            "detail": (
                f"Invoice {doc.invoice_number} already exists in the system. "
                "This document was held to prevent double payment."
                if doc and doc.invoice_number
                else ex.description or "Duplicate invoice detected."
            ),
        })

    elif code in ("MATCHING_MISMATCH", "PO_NOT_FOUND"):
        if code == "PO_NOT_FOUND":
            what_failed.append({
                "icon": "po",
                "heading": "Purchase Order not found",
                "detail": "No matching PO was found or linked to this invoice. "
                          "Procurement must verify before approval.",
            })
        if matching_detail:
            vr = matching_detail.get("variance_report") or {}
            for field, info in vr.items():
                if isinstance(info, dict) and not info.get("match", True):
                    what_failed.append({
                        "icon": "mismatch",
                        "heading": f"{field.replace('_', ' ').title()} mismatch",
                        "detail": (
                            f"Invoice: {info.get('invoice_value', '—')}  ·  "
                            f"PO/GRN: {info.get('po_value') or info.get('grn_value', '—')}  ·  "
                            f"Variance: {info.get('variance_pct', '—')}"
                        ),
                    })
            if not what_failed:
                what_failed.append({
                    "icon": "mismatch",
                    "heading": "Invoice does not match PO / GRN",
                    "detail": matching_detail.get("matching_notes") or ex.description or "",
                })

    elif code in ("PROFILE_VALIDATION_FAIL", "VALIDATION_FAILURE"):
        for vf in validation_failures:
            what_failed.append({
                "icon": "validation",
                "heading": vf["rule_name"] or vf["rule_code"],
                "detail": vf["reason"] or f"Expected {vf['expected_value']}, got {vf['actual_value']}",
            })

    elif code == "ARITHMETIC_ERROR" or any(
        "ARITHMETIC" in vf["rule_code"] for vf in validation_failures
    ):
        for vf in validation_failures:
            if "ARITHMETIC" in vf["rule_code"]:
                what_failed.append({
                    "icon": "arithmetic",
                    "heading": vf["rule_name"],
                    "detail": vf["reason"],
                })

    elif code == "OCR_LOW_CONFIDENCE":
        what_failed.append({
            "icon": "ocr",
            "heading": "Document scan quality too low",
            "detail": ex.description or "OCR confidence score fell below the minimum threshold. "
                      "Please re-upload a clearer scan of the document.",
        })

    elif code == "HANDWRITING_UNREADABLE":
        what_failed.append({
            "icon": "handwriting",
            "heading": "Handwritten document is unreadable",
            "detail": ex.description or "The AI could not extract reliable data from this handwritten document.",
        })

    elif code in ("POOR_IMAGE_QUALITY", "IMAGE_QUALITY"):
        what_failed.append({
            "icon": "image",
            "heading": "Poor image quality",
            "detail": ex.description or "The uploaded image is too blurry or low-resolution for accurate processing.",
        })

    else:
        # Generic fallback — use any validation failures plus the description
        for vf in validation_failures:
            what_failed.append({
                "icon": "validation",
                "heading": vf["rule_name"] or vf["rule_code"],
                "detail": vf["reason"],
            })
        if not what_failed and ex.description:
            what_failed.append({
                "icon": "generic",
                "heading": ex.title,
                "detail": ex.description,
            })

    return {
        "exception": _map_exception(ex),
        "document": document_snapshot,
        "what_failed": what_failed,
        "validation_failures": validation_failures,
        "matching_detail": matching_detail,
        "duplicate_comparison": duplicate_comparison,
    }


@router.post("/{exception_id}/resolve", response_model=ExceptionOut)
async def resolve_exception(
    exception_id: str,
    body: ExceptionResolve,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Ex).where(Ex.id == exception_id))
    ex = result.scalar_one_or_none()
    if not ex:
        raise HTTPException(status_code=404, detail="Exception not found")

    ex.status = body.status
    ex.resolution_notes = body.resolution_notes
    ex.resolved_by = str(current_user.id)
    ex.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return _map_exception(ex)


@router.post("/{exception_id}/assign", response_model=ExceptionOut)
async def assign_exception(
    exception_id: str,
    body: ExceptionAssign,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Ex).where(Ex.id == exception_id))
    ex = result.scalar_one_or_none()
    if not ex:
        raise HTTPException(status_code=404, detail="Exception not found")

    ex.assigned_to = body.assigned_to
    ex.status = ExceptionStatus.IN_PROGRESS
    await db.flush()
    return _map_exception(ex)


def _map_exception(e: Ex) -> ExceptionOut:
    return ExceptionOut(
        id=str(e.id),
        document_id=str(e.document_id),
        exception_code=e.exception_code,
        exception_type=e.exception_type,
        severity=e.severity,
        queue=e.queue,
        title=e.title,
        description=e.description,
        agent_raised_by=e.agent_raised_by,
        assigned_to=str(e.assigned_to) if e.assigned_to else None,
        assignee_name=None,
        status=e.status,
        sla_hours=e.sla_hours,
        sla_deadline=e.sla_deadline,
        resolution_notes=e.resolution_notes,
        resolved_at=e.resolved_at,
        escalation_count=e.escalation_count or 0,
        created_at=e.created_at,
    )
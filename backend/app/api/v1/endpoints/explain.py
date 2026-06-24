"""
Explainability endpoints — Phase 8.

Provides structured AI decision explanations, exception reasoning, and
approval recommendations synthesised from existing DB data + LangGraph state.

Architecture rule: APIs contain NO business logic — all synthesis happens here
by reading from the DB and composing a structured response.

Endpoints:
  GET /documents/{id}/explanation         → ExplainableDecision for a document
  GET /exceptions/{id}/explanation        → Why this exception was raised
  GET /approvals/{id}/recommendation      → AI recommendation for an approver
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.security import get_current_user
from app.models.models import (
    Document, MatchingResult, ValidationResult, User,
    Exception as Ex, Approval, AuditLog,
)

logger = logging.getLogger(__name__)

# Three separate routers — each prefixed so they slot cleanly into router.py
documents_explain_router = APIRouter(prefix="/documents", tags=["Explainability"])
exceptions_explain_router = APIRouter(prefix="/exceptions", tags=["Explainability"])
approvals_explain_router = APIRouter(prefix="/approvals", tags=["Explainability"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STATUS_TO_DECISION: Dict[str, str] = {
    "COMPLETED":             "AUTO_APPROVED",
    "POSTED":                "AUTO_APPROVED",
    "APPROVED":              "APPROVED",
    "PENDING_APPROVAL":      "NEEDS_APPROVAL",
    "AWAITING_APPROVAL":     "NEEDS_APPROVAL",
    "EXCEPTION":             "EXCEPTION_RAISED",
    "FAILED":                "REJECTED",
    "REJECTED":              "REJECTED",
    "HUMAN_REVIEW_REQUIRED": "NEEDS_HUMAN_REVIEW",
    "UNDER_REVIEW":          "NEEDS_HUMAN_REVIEW",
}

_DECISION_COLORS: Dict[str, str] = {
    "AUTO_APPROVED":      "success",
    "APPROVED":           "success",
    "NEEDS_APPROVAL":     "warning",
    "EXCEPTION_RAISED":   "error",
    "REJECTED":           "error",
    "NEEDS_HUMAN_REVIEW": "warning",
    "IN_PROGRESS":        "info",
}


def _direction(score: float, high: float = 0.85, low: float = 0.60) -> str:
    if score >= high:
        return "POSITIVE"
    if score >= low:
        return "WARNING"
    return "NEGATIVE"


async def _load_document(document_id: str, db: AsyncSession) -> Document:
    from app.api.v1.deps import resolve_document
    return await resolve_document(db, document_id)


# ---------------------------------------------------------------------------
# GET /documents/{document_id}/explanation
# ---------------------------------------------------------------------------

@documents_explain_router.get(
    "/{document_id}/explanation",
    summary="Structured AI decision explanation for a document",
)
async def get_document_explanation(
    document_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Synthesise a structured ExplainableDecision for any document.

    Data sources:
    - Document row (status, confidence, profile, amounts)
    - ValidationResult rows (pass/fail/warn per rule)
    - MatchingResult row (overall score + match breakdown)
    - Exception rows (raised exceptions)
    - LangGraph checkpointed state (when available — richer data)

    Falls back gracefully for documents processed by the Celery pipeline.
    """
    doc = await _load_document(document_id, db)

    # ── Load related records ──────────────────────────────────────────────
    vr_rows = (await db.execute(
        select(ValidationResult).where(ValidationResult.document_id == doc.id)
    )).scalars().all()

    mr_row = (await db.execute(
        select(MatchingResult).where(MatchingResult.document_id == doc.id)
    )).scalar_one_or_none()

    exc_rows = (await db.execute(
        select(Ex).where(Ex.document_id == doc.id)
    )).scalars().all()

    # ── Try LangGraph state for richer confidence data ────────────────────
    lg_confidence: Optional[Dict[str, Any]] = None
    lg_routing: Optional[Dict[str, Any]] = None
    try:
        from app.core.graph_registry import GraphRegistry
        registry = GraphRegistry.get_instance()
        if registry.is_ready():
            snapshot = registry.get_state("invoice_processing", str(doc.id))
            if snapshot and snapshot.values:
                wf = snapshot.values
                conf = getattr(wf, "confidence", None)
                routing = getattr(wf, "routing", None)
                if conf:
                    lg_confidence = (
                        conf.model_dump() if hasattr(conf, "model_dump") else vars(conf)
                    )
                if routing:
                    lg_routing = (
                        routing.model_dump() if hasattr(routing, "model_dump") else vars(routing)
                    )
    except Exception as exc:
        logger.debug("LangGraph state unavailable for explanation: %s", exc)

    # ── Derive decision ───────────────────────────────────────────────────
    decision = _STATUS_TO_DECISION.get(str(doc.status), "IN_PROGRESS")

    pass_count = sum(1 for v in vr_rows if v.status == "PASS")
    fail_count = sum(1 for v in vr_rows if v.status == "FAIL")
    warn_count = sum(1 for v in vr_rows if v.status == "WARNING")
    total_rules = len(vr_rows)
    val_pass_rate: Optional[float] = (pass_count / total_rules) if total_rules > 0 else None

    fail_validations = [v for v in vr_rows if v.status == "FAIL"]
    warn_validations = [v for v in vr_rows if v.status == "WARNING"]

    # ── Primary reason ────────────────────────────────────────────────────
    if decision == "EXCEPTION_RAISED" and exc_rows:
        primary_reason = exc_rows[0].title or exc_rows[0].description or "Exception raised during processing"
    elif decision == "REJECTED" and fail_validations:
        fv = fail_validations[0]
        primary_reason = f"Validation failed: {fv.reason or fv.rule_name or fv.rule_code}"
    elif decision in ("AUTO_APPROVED", "APPROVED"):
        primary_reason = (
            f"All {pass_count} validation rules passed"
            + (f" with a match score of {float(mr_row.overall_match_score)*100:.0f}%" if mr_row else "")
        )
    elif decision == "NEEDS_APPROVAL":
        if fail_validations:
            primary_reason = f"Validation failure requires approval: {fail_validations[0].reason or fail_validations[0].rule_name}"
        elif doc.total_amount:
            primary_reason = f"Invoice amount ₹{float(doc.total_amount):,.0f} requires approval per business profile {doc.business_profile or 'policy'}"
        else:
            primary_reason = f"Invoice requires approval per {doc.business_profile or 'business policy'}"
    elif decision == "NEEDS_HUMAN_REVIEW":
        if warn_validations:
            primary_reason = f"Human review required: {warn_validations[0].reason or warn_validations[0].rule_name}"
        else:
            primary_reason = "Invoice requires human review due to low confidence or ambiguous classification"
    elif decision == "IN_PROGRESS":
        primary_reason = f"Document is currently {doc.status.replace('_', ' ').lower()}"
    else:
        primary_reason = f"Document status: {doc.status}"

    # ── Contributing factors ──────────────────────────────────────────────
    factors: List[Dict[str, Any]] = []

    if total_rules > 0:
        pct = f"{val_pass_rate * 100:.0f}%" if val_pass_rate is not None else "N/A"
        factors.append({
            "factor_name": "Validation Rules",
            "weight": 0.30,
            "value": f"{pass_count}/{total_rules} passed ({pct})",
            "direction": "POSITIVE" if fail_count == 0 else ("NEGATIVE" if fail_count > 2 else "WARNING"),
        })

    if mr_row:
        ms = float(mr_row.overall_match_score or 0)
        factors.append({
            "factor_name": "Invoice Match Score",
            "weight": 0.25,
            "value": f"{ms * 100:.0f}% ({mr_row.match_status})",
            "direction": _direction(ms),
        })

    if doc.ai_profile_confidence:
        pc = float(doc.ai_profile_confidence)
        factors.append({
            "factor_name": "Business Profile Confidence",
            "weight": 0.20,
            "value": f"{pc * 100:.0f}% — {doc.business_profile or 'Unknown'}",
            "direction": _direction(pc),
        })

    if doc.ocr_confidence is not None:
        oc = float(doc.ocr_confidence)
        factors.append({
            "factor_name": "OCR Confidence",
            "weight": 0.15,
            "value": f"{oc * 100:.0f}%",
            "direction": _direction(oc, high=0.85, low=0.70),
        })

    if exc_rows:
        factors.append({
            "factor_name": "Exceptions Raised",
            "weight": 0.10,
            "value": f"{len(exc_rows)} exception(s) — severity: {exc_rows[0].severity}",
            "direction": "NEGATIVE",
        })

    if doc.total_amount:
        factors.append({
            "factor_name": "Invoice Amount",
            "weight": 0.05,
            "value": f"₹{float(doc.total_amount):,.0f}",
            "direction": "NEUTRAL",
        })

    # ── Confidence breakdown ──────────────────────────────────────────────
    if lg_confidence:
        # Prefer LangGraph data when available
        confidence_breakdown = {
            "overall":            lg_confidence.get("overall_score"),
            "confidence_band":    lg_confidence.get("confidence_band"),
            "ocr_confidence":     float(doc.ocr_confidence) if doc.ocr_confidence is not None else None,
            "validation_pass_rate": round(val_pass_rate, 4) if val_pass_rate is not None else None,
            "profile_confidence": float(doc.ai_profile_confidence) if doc.ai_profile_confidence else None,
            "match_score":        float(mr_row.overall_match_score) if mr_row else None,
            "component_scores":   lg_confidence.get("component_scores", {}),
        }
    else:
        # Synthesise from DB fields
        ai_conf = float(doc.ai_profile_confidence or 0.0)
        match_score = float(mr_row.overall_match_score) if mr_row else None
        vr_score = val_pass_rate if val_pass_rate is not None else 0.0

        # Weighted average of available signals
        weights, weighted_sum = 0.0, 0.0
        if doc.ai_profile_confidence:
            weighted_sum += ai_conf * 0.40; weights += 0.40
        if match_score is not None:
            weighted_sum += match_score * 0.35; weights += 0.35
        if val_pass_rate is not None:
            weighted_sum += vr_score * 0.25; weights += 0.25
        overall = round(weighted_sum / weights, 4) if weights > 0 else 0.0

        confidence_breakdown = {
            "overall":            overall,
            "confidence_band":    "HIGH" if overall >= 0.85 else ("MEDIUM" if overall >= 0.60 else "LOW"),
            "ocr_confidence":     float(doc.ocr_confidence) if doc.ocr_confidence is not None else None,
            "validation_pass_rate": round(val_pass_rate, 4) if val_pass_rate is not None else None,
            "profile_confidence": float(doc.ai_profile_confidence) if doc.ai_profile_confidence else None,
            "match_score":        match_score,
            "component_scores":   {},
        }

    # ── Alternative decisions ─────────────────────────────────────────────
    alt_decisions: List[Dict[str, str]] = []
    if decision in ("NEEDS_APPROVAL", "NEEDS_HUMAN_REVIEW") and fail_count == 0:
        alt_decisions.append({
            "decision": "AUTO_APPROVE",
            "reason": "Would auto-approve if invoice amount is within the auto-approve threshold and all validations pass",
            "would_apply_if": "total_amount ≤ auto_approve_threshold AND confidence ≥ 0.85",
        })
    if decision == "EXCEPTION_RAISED":
        alt_decisions.append({
            "decision": "NEEDS_APPROVAL",
            "reason": "Would route to approval after exception is resolved",
            "would_apply_if": "exception.status = RESOLVED",
        })
    if decision == "NEEDS_APPROVAL" and mr_row and float(mr_row.overall_match_score or 0) >= 0.85:
        alt_decisions.append({
            "decision": "AUTO_APPROVE",
            "reason": "Match score is sufficient; routing to approval due to amount or policy threshold only",
            "would_apply_if": "total_amount ≤ auto_approve_threshold",
        })

    # ── Rules triggered ───────────────────────────────────────────────────
    rules_triggered = list({
        (v.rule_code or v.rule_name or "UNKNOWN")
        for v in fail_validations
        if v.rule_code or v.rule_name
    })

    return {
        "document_id": document_id,
        "decision":             decision,
        "decision_color":       _DECISION_COLORS.get(decision, "default"),
        "primary_reason":       primary_reason,
        "contributing_factors": factors,
        "confidence_breakdown": confidence_breakdown,
        "rules_evaluated":      total_rules,
        "rules_passed":         pass_count,
        "rules_warned":         warn_count,
        "rules_failed":         fail_count,
        "rules_triggered":      rules_triggered,
        "alternative_decisions": alt_decisions,
        "exceptions_raised":    len(exc_rows),
        "pipeline":             "langgraph" if lg_confidence else "celery",
        "generated_at":         datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /exceptions/{exception_id}/explanation
# ---------------------------------------------------------------------------

@exceptions_explain_router.get(
    "/{exception_id}/explanation",
    summary="Structured explanation of why an exception was raised",
)
async def get_exception_explanation(
    exception_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Return a structured explanation for an exception record.

    Includes the exception type, severity, the agent that raised it,
    SLA metadata, resolution status, and a suggested resolution.
    """
    exc_result = await db.execute(
        select(Ex).where(Ex.id == exception_id)
    )
    exc = exc_result.scalar_one_or_none()
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found")

    doc_result = await db.execute(
        select(Document).where(Document.id == exc.document_id)
    )
    doc = doc_result.scalar_one_or_none()

    # Derive a human-readable suggested resolution based on exception type
    RESOLUTION_HINTS: Dict[str, str] = {
        "DUPLICATE":            "Verify if this is a duplicate submission. If so, reject. Otherwise mark as unique.",
        "VENDOR_MISMATCH":      "Match the vendor name against the ERP master. Update the vendor mapping if needed.",
        "AMOUNT_MISMATCH":      "Compare invoice total against the PO/GRN. Request a credit note if overbilled.",
        "GST_INVALID":          "Request a corrected invoice with a valid GSTIN from the vendor.",
        "PAN_INVALID":          "Verify vendor PAN against TRACES. Update vendor master if incorrect.",
        "PO_NOT_FOUND":         "Confirm the PO number with the procurement team. Create a new PO if required.",
        "GRN_NOT_FOUND":        "Confirm goods receipt with the warehouse team before processing payment.",
        "TAX_MISMATCH":         "Recalculate GST based on the applicable rate. Consult tax team if uncertain.",
        "LOW_OCR_QUALITY":      "Request a clearer scan or digital PDF from the vendor.",
        "BUDGET_EXCEEDED":      "Obtain budget exception approval from the finance controller.",
    }

    exc_code = str(exc.exception_code or "")
    suggested = RESOLUTION_HINTS.get(exc_code, "Review the exception details and coordinate with the relevant team to resolve.")

    return {
        "exception_id":       exception_id,
        "document_id":        str(exc.document_id),
        "document_ref":       doc.document_id if doc else None,
        "exception_code":     exc.exception_code,
        "exception_type":     exc.exception_type,
        "severity":           exc.severity,
        "queue":              exc.queue,
        "title":              exc.title,
        "description":        exc.description,
        "raised_by_agent":    exc.agent_raised_by,
        "status":             exc.status,
        "resolution_type":    exc.resolution_type,
        "sla_hours":          exc.sla_hours,
        "sla_deadline":       exc.sla_deadline.isoformat() if exc.sla_deadline else None,
        "created_at":         exc.created_at.isoformat() if exc.created_at else None,
        "resolved_at":        exc.resolved_at.isoformat() if exc.resolved_at else None,
        "resolution_notes":   exc.resolution_notes,
        "suggested_resolution": suggested,
        "is_overdue": (
            exc.sla_deadline is not None
            and exc.status not in ("RESOLVED", "CLOSED")
            and datetime.now(timezone.utc) > exc.sla_deadline
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /approvals/{approval_id}/recommendation
# ---------------------------------------------------------------------------

@approvals_explain_router.get(
    "/{approval_id}/recommendation",
    summary="AI recommendation for an approver",
)
async def get_approval_recommendation(
    approval_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Return a structured AI recommendation for an approval request.

    Synthesises a recommendation (APPROVE / REJECT / ESCALATE / REQUEST_INFO)
    from the document's validation results, matching score, business profile,
    and amount vs authority.
    """
    approval_result = await db.execute(
        select(Approval).where(Approval.id == approval_id)
    )
    approval = approval_result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    doc_result = await db.execute(
        select(Document).where(Document.id == approval.document_id)
    )
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    vr_rows = (await db.execute(
        select(ValidationResult).where(ValidationResult.document_id == doc.id)
    )).scalars().all()

    mr_row = (await db.execute(
        select(MatchingResult).where(MatchingResult.document_id == doc.id)
    )).scalar_one_or_none()

    exc_rows = (await db.execute(
        select(Ex).where(Ex.document_id == doc.id)
    )).scalars().all()

    pass_count = sum(1 for v in vr_rows if v.status == "PASS")
    fail_count = sum(1 for v in vr_rows if v.status == "FAIL")
    total_rules = len(vr_rows)
    val_pass_rate = (pass_count / total_rules) if total_rules > 0 else None

    match_score = float(mr_row.overall_match_score) if mr_row else None
    open_exceptions = [e for e in exc_rows if e.status not in ("RESOLVED", "CLOSED")]

    # ── Derive recommendation ─────────────────────────────────────────────
    risk_factors: List[str] = []
    supporting_evidence: List[str] = []

    if fail_count > 0:
        risk_factors.append(f"{fail_count} validation rule(s) failed")
    if open_exceptions:
        risk_factors.append(f"{len(open_exceptions)} open exception(s) not yet resolved")
    if match_score is not None and match_score < 0.80:
        risk_factors.append(f"Match score {match_score * 100:.0f}% is below 80% threshold")

    if pass_count > 0:
        supporting_evidence.append(f"{pass_count}/{total_rules} validation rules passed")
    if match_score is not None and match_score >= 0.85:
        supporting_evidence.append(f"Invoice/PO/GRN match score: {match_score * 100:.0f}%")
    if doc.ai_profile_confidence and float(doc.ai_profile_confidence) >= 0.80:
        supporting_evidence.append(f"Business profile classified with {float(doc.ai_profile_confidence) * 100:.0f}% confidence")

    # Recommendation logic
    if open_exceptions or fail_count > 0:
        recommendation = "REJECT"
        recommendation_reason = (
            f"There are {len(open_exceptions)} unresolved exception(s) and {fail_count} validation failure(s). "
            "Do not approve until these are resolved."
        )
    elif match_score is not None and match_score < 0.70:
        recommendation = "REQUEST_INFO"
        recommendation_reason = (
            f"Match score of {match_score * 100:.0f}% is too low to approve. "
            "Request clarification from the vendor or AP team."
        )
    elif val_pass_rate is not None and val_pass_rate >= 0.95 and (match_score is None or match_score >= 0.85):
        recommendation = "APPROVE"
        recommendation_reason = (
            f"All validations pass ({pass_count}/{total_rules})"
            + (f" with a match score of {match_score * 100:.0f}%." if match_score else ".")
        )
    else:
        recommendation = "ESCALATE"
        recommendation_reason = (
            "Mixed signals — some validations passed but confidence is not high enough for clear approval. "
            "Escalate to senior approver."
        )

    amount_analysis: Dict[str, Any] = {
        "invoice_amount":  float(doc.invoice_amount) if doc.invoice_amount else None,
        "tax_amount":      float(doc.tax_amount) if doc.tax_amount else None,
        "total_amount":    float(doc.total_amount) if doc.total_amount else None,
        "authority_limit": float(approval.authority_amount) if approval.authority_amount else None,
        "within_authority": (
            float(doc.total_amount) <= float(approval.authority_amount)
            if doc.total_amount and approval.authority_amount else None
        ),
    }

    return {
        "approval_id":          approval_id,
        "document_id":          str(doc.id),
        "document_ref":         doc.document_id,
        "business_profile":     doc.business_profile,
        "approval_level":       approval.approval_level,
        "recommendation":       recommendation,
        "recommendation_color": {
            "APPROVE":       "success",
            "REJECT":        "error",
            "REQUEST_INFO":  "warning",
            "ESCALATE":      "warning",
        }.get(recommendation, "default"),
        "recommendation_reason": recommendation_reason,
        "risk_factors":          risk_factors,
        "supporting_evidence":   supporting_evidence,
        "amount_analysis":       amount_analysis,
        "validation_summary": {
            "total":  total_rules,
            "passed": pass_count,
            "failed": fail_count,
        },
        "match_score": match_score,
        "open_exceptions": len(open_exceptions),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

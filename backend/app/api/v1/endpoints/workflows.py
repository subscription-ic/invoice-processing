"""
Workflow endpoints — Phase 5.

New endpoints that expose LangGraph workflow state, HITL resume/approve,
confidence details, timeline, and agent trace.

All existing endpoints in documents.py, approvals.py, exceptions.py are
UNCHANGED — full backward compatibility.

New endpoints require authentication.
X-Tenant-ID header is optional (defaults to "default").
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.security import get_current_user
from app.middleware.tenant_middleware import get_tenant_id
from app.models.models import AuditLog, Document, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["Workflows"])


# ---------------------------------------------------------------------------
# Request / response schemas (Phase 5 only — no impact on existing schemas)
# ---------------------------------------------------------------------------

class ReviewDecision(BaseModel):
    decision: str = "APPROVED"       # APPROVED | REJECTED | CORRECTED | ESCALATE
    corrections: Optional[Dict[str, Any]] = None
    resume_node: Optional[str] = "validate"
    comments: Optional[str] = None
    reviewer_id: Optional[str] = None


class ApprovalDecision(BaseModel):
    decision: str = "APPROVED"       # APPROVED | REJECTED | DELEGATE
    comments: Optional[str] = None
    approver_id: Optional[str] = None
    delegate_to: Optional[str] = None


class ExceptionResolution(BaseModel):
    resolution_type: str              # MANUAL_FIX | AUTO_FIX | OVERRIDE | REJECT
    resolution_notes: Optional[str] = None
    resolver_id: Optional[str] = None
    corrected_fields: Optional[Dict[str, Any]] = None


class PromptActivateRequest(BaseModel):
    version: str


class ConfigPatchRequest(BaseModel):
    updates: Dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_document_or_404(document_id: str, db: AsyncSession) -> Document:
    from app.api.v1.deps import resolve_document
    return await resolve_document(db, document_id)


def _get_registry():
    from app.core.graph_registry import GraphRegistry
    registry = GraphRegistry.get_instance()
    if not registry.is_ready():
        raise HTTPException(status_code=503, detail="LangGraph pipeline not initialised")
    return registry


def _invoke_graph_sync(graph, command_or_state, config: dict) -> Any:
    """Run a synchronous graph.invoke in a thread pool (non-blocking for FastAPI)."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(graph.invoke, command_or_state, config)
        return future.result(timeout=300)


# ---------------------------------------------------------------------------
# GET /workflows/{document_id}/state
# ---------------------------------------------------------------------------

@router.get("/{document_id}/state", summary="Full LangGraph WorkflowState")
async def get_workflow_state(
    document_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Return the full LangGraph WorkflowState for a document.

    Falls back to the ORM WorkflowState (legacy Celery path) when
    the LangGraph pipeline has not run for this document.
    """
    doc = await _get_document_or_404(document_id, db)
    thread_id = str(doc.id)

    # Try LangGraph checkpointer first
    try:
        registry = _get_registry()
        snapshot = registry.get_state("invoice_processing", thread_id)
        if snapshot and snapshot.values:
            wf_state = snapshot.values
            if hasattr(wf_state, "model_dump"):
                return wf_state.model_dump(mode="json")
            return wf_state
    except HTTPException:
        pass
    except Exception as exc:
        logger.debug(f"LangGraph state not found for {thread_id}: {exc}")

    # Fallback: ORM WorkflowState
    from app.models.models import WorkflowState as OrmWfState
    result = await db.execute(
        select(OrmWfState).where(OrmWfState.document_id == doc.id)
    )
    orm_state = result.scalar_one_or_none()
    if not orm_state:
        raise HTTPException(status_code=404, detail="Workflow state not found")

    return {
        "document_id": str(doc.id),
        "status": str(doc.status),
        "current_stage": orm_state.current_stage,
        "current_agent": orm_state.current_agent,
        "progress_percent": orm_state.progress_percent,
        "error_message": orm_state.error_message,
        "stage_history": orm_state.stage_history or [],
        "retry_count": orm_state.retry_count,
        "started_at": orm_state.started_at.isoformat() if orm_state.started_at else None,
        "completed_at": orm_state.completed_at.isoformat() if orm_state.completed_at else None,
        "pipeline": "celery",
    }


# ---------------------------------------------------------------------------
# GET /workflows/{document_id}/timeline
# ---------------------------------------------------------------------------

@router.get("/{document_id}/timeline", summary="Agent execution timeline")
async def get_workflow_timeline(
    document_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    """
    Ordered timeline of agent execution events for a document.
    Reads from audit_logs, sorted by timestamp ascending.
    """
    doc = await _get_document_or_404(document_id, db)

    result = await db.execute(
        select(AuditLog)
        .where(
            (AuditLog.document_id == doc.id)
            | (AuditLog.document_id == document_id)
        )
        .order_by(AuditLog.timestamp)
    )
    logs = result.scalars().all()

    return [
        {
            "event_id": str(l.id),
            "agent": l.agent,
            "action": l.action,
            "stage": l.stage,
            "entity_type": l.entity_type,
            "after_state": l.after_state,
            "timestamp": l.timestamp.isoformat() if l.timestamp else None,
        }
        for l in logs
    ]


# ---------------------------------------------------------------------------
# GET /workflows/{document_id}/confidence
# ---------------------------------------------------------------------------

@router.get("/{document_id}/confidence", summary="Confidence score breakdown")
async def get_workflow_confidence(
    document_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    """
    Per-component confidence breakdown from ConfidenceAgent output.
    Reads from LangGraph checkpointed state.
    """
    doc = await _get_document_or_404(document_id, db)
    thread_id = str(doc.id)

    try:
        registry = _get_registry()
        snapshot = registry.get_state("invoice_processing", thread_id)
        if snapshot and snapshot.values:
            wf = snapshot.values
            conf = getattr(wf, "confidence", None)
            routing = getattr(wf, "routing", None)
            if conf:
                return {
                    "overall_score": conf.overall_score,
                    "confidence_band": conf.confidence_band,
                    "component_scores": conf.component_scores,
                    "contributing_factors": [
                        f.model_dump() for f in (conf.contributing_factors or [])
                    ],
                    "summary": conf.summary,
                    "auto_approve_eligible": routing.auto_approve_eligible if routing else None,
                    "requires_human_review": routing.requires_human_review if routing else None,
                }
    except Exception as exc:
        logger.debug(f"Could not read confidence from LangGraph for {thread_id}: {exc}")

    # Fallback: read from Document table
    return {
        "overall_score": float(doc.ai_profile_confidence or 0.0),
        "confidence_band": None,
        "component_scores": {},
        "contributing_factors": [],
        "summary": "Confidence data from legacy Celery pipeline",
        "pipeline": "celery",
    }


# ---------------------------------------------------------------------------
# GET /workflows/{document_id}/agent-trace
# ---------------------------------------------------------------------------

@router.get("/{document_id}/agent-trace", summary="Per-agent execution log")
async def get_agent_trace(
    document_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    """
    Per-agent execution log with before/after state, agent name, and duration.
    """
    doc = await _get_document_or_404(document_id, db)

    result = await db.execute(
        select(AuditLog)
        .where(
            (AuditLog.document_id == doc.id)
            | (AuditLog.document_id == document_id)
        )
        .order_by(AuditLog.timestamp)
    )
    logs = result.scalars().all()

    return [
        {
            "event_id": str(l.id),
            "agent": l.agent,
            "action": l.action,
            "stage": l.stage,
            "before_state": l.before_state,
            "after_state": l.after_state,
            "metadata": l.log_metadata,
            "timestamp": l.timestamp.isoformat() if l.timestamp else None,
        }
        for l in logs
    ]


# ---------------------------------------------------------------------------
# GET /workflows/{document_id}/review
# ---------------------------------------------------------------------------

@router.get("/{document_id}/review", summary="Human review pack")
async def get_review_pack(
    document_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    """
    Return the review pack for a document suspended at the human_review_interrupt node.
    Calls HumanReviewAgent.build_review_context() against the checkpointed state.
    """
    doc = await _get_document_or_404(document_id, db)
    thread_id = str(doc.id)

    try:
        registry = _get_registry()
        snapshot = registry.get_state("invoice_processing", thread_id)
        if snapshot and snapshot.values:
            wf_state = snapshot.values
            from core.agents.human_review_agent import HumanReviewAgent
            agent = HumanReviewAgent()
            return agent.build_review_context(wf_state)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(f"Could not build review context for {thread_id}: {exc}")
        raise HTTPException(
            status_code=404,
            detail="No LangGraph review context found. Document may be on legacy pipeline.",
        )

    raise HTTPException(status_code=404, detail="No workflow state found for review")


# ---------------------------------------------------------------------------
# POST /workflows/{document_id}/resume
# ---------------------------------------------------------------------------

@router.post("/{document_id}/resume", summary="Submit human review decision")
async def resume_workflow(
    document_id: str,
    body: ReviewDecision,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    """
    Resume a workflow suspended at the human_review_interrupt node.

    Accepts the reviewer's decision, applies corrections if any, and
    resumes the LangGraph InvoiceProcessingGraph from the correct node.
    """
    from langgraph.types import Command

    doc = await _get_document_or_404(document_id, db)
    thread_id = str(doc.id)
    registry = _get_registry()

    resume_value = {
        "decision": body.decision,
        "corrections": body.corrections,
        "resume_node": body.resume_node or "validate",
        "comments": body.comments,
        "reviewer_id": body.reviewer_id or str(current_user.id),
    }

    config = {"configurable": {"thread_id": thread_id}}
    graph = registry.get_graph("invoice_processing")

    try:
        result_state = await asyncio.to_thread(
            graph.invoke, Command(resume=resume_value), config
        )
        final_status = None
        if hasattr(result_state, "workflow"):
            final_status = result_state.workflow.status

        return {
            "status": "resumed",
            "document_id": document_id,
            "workflow_status": final_status,
            "message": f"Workflow resumed with decision={body.decision}",
        }
    except Exception as exc:
        exc_name = type(exc).__name__
        if "Interrupt" in exc_name:
            return {
                "status": "re_interrupted",
                "document_id": document_id,
                "message": "Workflow paused again at a subsequent interrupt point",
            }
        logger.error(f"Error resuming workflow {thread_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Resume failed: {exc}")


# ---------------------------------------------------------------------------
# POST /workflows/{document_id}/approve
# ---------------------------------------------------------------------------

@router.post("/{document_id}/approve", summary="Submit approval decision")
async def approve_workflow(
    document_id: str,
    body: ApprovalDecision,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    """
    Submit an approval decision for a workflow suspended in ApprovalGraph.

    Maps to POST /approvals/{id}/action for backward compatibility.
    Also resumes the LangGraph ApprovalGraph when the pipeline is active.
    """
    from app.core.config import settings

    doc = await _get_document_or_404(document_id, db)

    if settings.USE_LANGGRAPH_PIPELINE:
        from langgraph.types import Command

        thread_id = str(doc.id)
        registry = _get_registry()

        resume_value = {
            "decision": body.decision,
            "comments": body.comments,
            "approver_id": body.approver_id or str(current_user.id),
        }
        config = {"configurable": {"thread_id": thread_id}}

        try:
            graph = registry.get_graph("approval")
            result_state = await asyncio.to_thread(
                graph.invoke, Command(resume=resume_value), config
            )
            final_status = None
            if hasattr(result_state, "workflow"):
                final_status = result_state.workflow.status

            return {
                "status": "decision_recorded",
                "document_id": document_id,
                "workflow_status": final_status,
                "decision": body.decision,
            }
        except Exception as exc:
            exc_name = type(exc).__name__
            if "Interrupt" in exc_name:
                return {
                    "status": "awaiting_next_level",
                    "document_id": document_id,
                    "message": "Decision recorded; next approval level pending",
                }
            logger.error(f"Error processing approval for {thread_id}: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Approval failed: {exc}")

    # Legacy path — delegate to the existing approval endpoint logic
    raise HTTPException(
        status_code=400,
        detail="LangGraph pipeline not active. Use POST /approvals/{id}/action for legacy approvals.",
    )


# ---------------------------------------------------------------------------
# POST /workflows/{document_id}/exceptions/{exception_id}/resolve
# ---------------------------------------------------------------------------

@router.post(
    "/{document_id}/exceptions/{exception_id}/resolve",
    summary="Resolve an exception (LangGraph path)",
)
async def resolve_workflow_exception(
    document_id: str,
    exception_id: str,
    body: ExceptionResolution,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    """
    Submit exception resolution and resume the LangGraph ExceptionGraph.
    Also updates the ORM Exception record for backward compatibility.
    """
    from app.core.config import settings
    from app.models.models import Exception as Ex
    from datetime import timezone

    doc = await _get_document_or_404(document_id, db)

    # Update ORM record (backward compat — same as existing exceptions endpoint)
    exc_result = await db.execute(select(Ex).where(Ex.id == exception_id))
    orm_exc = exc_result.scalar_one_or_none()
    if orm_exc:
        orm_exc.resolution_notes = body.resolution_notes
        orm_exc.resolved_by = str(current_user.id)
        orm_exc.resolved_at = datetime.now(timezone.utc)
        from app.models.models import ExceptionStatus
        orm_exc.status = ExceptionStatus.RESOLVED
        await db.flush()

    if settings.USE_LANGGRAPH_PIPELINE:
        from langgraph.types import Command

        thread_id = str(doc.id)
        registry = _get_registry()

        resume_value = {
            "resolution_type": body.resolution_type,
            "resolution_notes": body.resolution_notes,
            "resolver_id": body.resolver_id or str(current_user.id),
            "corrected_fields": body.corrected_fields,
        }
        config = {"configurable": {"thread_id": thread_id}}

        try:
            graph = registry.get_graph("exception")
            result_state = await asyncio.to_thread(
                graph.invoke, Command(resume=resume_value), config
            )
            return {
                "status": "resolved",
                "document_id": document_id,
                "exception_id": exception_id,
                "resolution_type": body.resolution_type,
            }
        except Exception as exc:
            logger.warning(f"ExceptionGraph resume failed for {thread_id}: {exc}")

    return {
        "status": "resolved",
        "document_id": document_id,
        "exception_id": exception_id,
        "pipeline": "celery",
    }


# ---------------------------------------------------------------------------
# GET /workflows/{document_id}/stream  (SSE — stub)
# ---------------------------------------------------------------------------

@router.get("/{document_id}/stream", summary="Server-Sent Events: live workflow updates")
async def stream_workflow(
    document_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Server-Sent Events endpoint for real-time workflow status updates.
    Full implementation in Phase 9 (Notification Engine).
    Currently returns a single status event and closes.
    """
    async def _generator():
        yield f"data: {{\"document_id\": \"{document_id}\", \"event\": \"connected\"}}\n\n"

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

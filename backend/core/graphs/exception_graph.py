"""
ExceptionGraph — classify, assign, notify, and manage resolution of exceptions.

Interrupt Point:
  exception_wait — suspends after notification; resumes when resolver
  POSTs to /workflows/{id}/exceptions/{exc_id}/resolve
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from core.state.workflow_state import WorkflowState


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def exception_classify_node(state: WorkflowState) -> WorkflowState:
    from core.agents.exception_agent import ExceptionAgent
    return ExceptionAgent().run(state)


def exception_assign_node(state: WorkflowState) -> WorkflowState:
    """Assign exception to a specific user/queue (stub — full assignment in Phase 9)."""
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    doc_id = state.workflow.document_id
    audit_tool.run(AuditEventInput(
        document_id=doc_id, entity_type="EXCEPTION", entity_id=state.exception.exception_id or doc_id,
        action="EXCEPTION_ASSIGNED", agent_name="exception_graph",
        after_state={"queue": state.exception.assigned_queue, "assigned_to": state.exception.assigned_to},
        stage="EXCEPTION",
    ))
    return state.model_copy(deep=True, update={
        "workflow": state.workflow.model_copy(update={
            "status": "EXCEPTION_ASSIGNED",
            "updated_at": datetime.now(timezone.utc),
        }),
    })


def exception_notify_node(state: WorkflowState) -> WorkflowState:
    from core.agents.notification_agent import NotificationAgent
    return NotificationAgent(config={"event_type": "EXCEPTION_RAISED"}).run(state)


def exception_wait_node(state: WorkflowState) -> WorkflowState:
    """
    HITL interrupt — waits for resolver to POST an ExceptionResolution.

    Resume value keys: resolution_type, resolution_notes, corrected_fields, resolver_id
    """
    exc_id = state.exception.exception_id
    resume_value: Dict[str, Any] = interrupt({
        "interrupt_id": "EXCEPTION_AWAITING_RESOLUTION",
        "document_id": state.workflow.document_id,
        "exception_id": exc_id,
        "exception_type": state.exception.exception_type,
        "queue": state.exception.assigned_queue,
        "sla_deadline": str(state.exception.sla_deadline or ""),
    })

    resolution_type = resume_value.get("resolution_type", "MANUAL_FIX")
    notes = resume_value.get("resolution_notes", "")
    resolver_id = resume_value.get("resolver_id", "unknown")

    return state.model_copy(deep=True, update={
        "exception": state.exception.model_copy(update={
            "resolution_status": "IN_PROGRESS",
            "assigned_to": resolver_id,
            "resolution_type": resolution_type,
        }),
        "workflow": state.workflow.model_copy(update={
            "status": "EXCEPTION_RESOLVING",
            "updated_at": datetime.now(timezone.utc),
        }),
    })


def exception_evaluate_node(state: WorkflowState) -> WorkflowState:
    """Evaluate resolution attempt and mark resolved."""
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    doc_id = state.workflow.document_id

    # Simple rule: resolution is valid if type is set
    is_valid = state.exception.resolution_type is not None

    if is_valid:
        audit_tool.run(AuditEventInput(
            document_id=doc_id, entity_type="EXCEPTION",
            entity_id=state.exception.exception_id or doc_id,
            action="EXCEPTION_RESOLVED", agent_name="exception_graph",
            after_state={"resolution_type": state.exception.resolution_type},
            stage="EXCEPTION",
        ))
        return state.model_copy(deep=True, update={
            "exception": state.exception.model_copy(update={"resolution_status": "RESOLVED"}),
            "workflow": state.workflow.model_copy(update={
                "status": "EXCEPTION_RESOLVED",
                "updated_at": datetime.now(timezone.utc),
            }),
        })

    # Invalid — re-assign
    return state.model_copy(deep=True, update={
        "exception": state.exception.model_copy(update={"resolution_status": "OPEN"}),
        "workflow": state.workflow.model_copy(update={
            "status": "EXCEPTION_REASSIGNED",
            "updated_at": datetime.now(timezone.utc),
        }),
    })


def exception_resolved_node(state: WorkflowState) -> WorkflowState:
    from core.agents.audit_agent import AuditAgent
    return AuditAgent().run(state)


def exception_escalate_node(state: WorkflowState) -> WorkflowState:
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    new_level = state.exception.escalation_level + 1
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="EXCEPTION",
        entity_id=state.exception.exception_id or state.workflow.document_id,
        action="EXCEPTION_ESCALATED", agent_name="exception_graph",
        after_state={"escalation_level": new_level},
        stage="EXCEPTION",
    ))
    return state.model_copy(deep=True, update={
        "exception": state.exception.model_copy(update={"escalation_level": new_level}),
        "workflow": state.workflow.model_copy(update={
            "status": "EXCEPTION_ESCALATED",
            "updated_at": datetime.now(timezone.utc),
        }),
    })


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def _route_after_wait(state: WorkflowState) -> str:
    rt = state.exception.resolution_type
    if rt == "OVERRIDE":
        return "exception_resolved"
    if rt == "AUTO_FIX":
        # RetryGraph handles automated re-run; here we just mark resolved
        return "exception_resolved"
    return "exception_evaluate"


def _route_after_evaluate(state: WorkflowState) -> str:
    if state.exception.resolution_status == "RESOLVED":
        return "exception_resolved"
    return "exception_assign"  # re-assign


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_exception_graph(checkpointer=None) -> Any:
    from core.graphs.checkpointer import get_checkpointer

    builder = StateGraph(WorkflowState)

    builder.add_node("exception_classify", exception_classify_node)
    builder.add_node("exception_assign", exception_assign_node)
    builder.add_node("exception_notify", exception_notify_node)
    builder.add_node("exception_wait", exception_wait_node)
    builder.add_node("exception_evaluate", exception_evaluate_node)
    builder.add_node("exception_resolved", exception_resolved_node)
    builder.add_node("exception_escalate", exception_escalate_node)

    builder.set_entry_point("exception_classify")
    builder.add_edge("exception_classify", "exception_assign")
    builder.add_edge("exception_assign", "exception_notify")
    builder.add_edge("exception_notify", "exception_wait")

    builder.add_conditional_edges("exception_wait", _route_after_wait, {
        "exception_evaluate": "exception_evaluate",
        "exception_resolved": "exception_resolved",
    })

    builder.add_conditional_edges("exception_evaluate", _route_after_evaluate, {
        "exception_resolved": "exception_resolved",
        "exception_assign": "exception_assign",
    })

    builder.add_edge("exception_resolved", END)
    builder.add_edge("exception_escalate", END)

    cp = checkpointer or get_checkpointer()
    return builder.compile(checkpointer=cp)

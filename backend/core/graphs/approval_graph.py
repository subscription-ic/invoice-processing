"""
ApprovalGraph — multi-level approval workflow with HITL interrupt per level.

Interrupt Point:
  approval_wait — suspends after notifying the current-level approver.
  Resumes when approver POSTs to /workflows/{id}/approve.

After all levels approved: sets approval.final_decision=APPROVED and
InvoiceProcessingGraph resumes at erp_post.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from core.state.workflow_state import ApprovalLevel, WorkflowState


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def approval_prepare_node(state: WorkflowState) -> WorkflowState:
    from core.agents.approval_agent import ApprovalAgent
    return ApprovalAgent().run(state)


def approval_request_node(state: WorkflowState) -> WorkflowState:
    """Create the approval task for the current level."""
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    level = state.approval.current_level or 1
    levels = state.approval.approval_levels or []
    approver = levels[level - 1] if len(levels) >= level else None
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="APPROVAL",
        entity_id=state.approval.approval_id or state.workflow.document_id,
        action="APPROVAL_REQUESTED", agent_name="approval_graph",
        after_state={"level": level, "approver": approver.approver_id if approver else None},
        stage="APPROVAL",
    ))
    return state.model_copy(deep=True, update={
        "workflow": state.workflow.model_copy(update={
            "status": f"APPROVAL_L{level}_PENDING",
            "updated_at": datetime.now(timezone.utc),
        }),
    })


def approval_notify_node(state: WorkflowState) -> WorkflowState:
    from core.agents.notification_agent import NotificationAgent
    level = state.approval.current_level or 1
    return NotificationAgent(config={"event_type": f"APPROVAL_L{level}_REQUESTED"}).run(state)


def approval_wait_node(state: WorkflowState) -> WorkflowState:
    """
    HITL interrupt — waits for approver decision.

    Resume value: { decision, comments, approver_id }
    decision: APPROVED | REJECTED | DELEGATE
    """
    level = state.approval.current_level or 1
    levels = state.approval.approval_levels or []
    approver = levels[level - 1] if len(levels) >= level else None

    resume_value: Dict[str, Any] = interrupt({
        "interrupt_id": f"APPROVAL_L{level}_PENDING",
        "document_id": state.workflow.document_id,
        "approval_id": state.approval.approval_id,
        "level": level,
        "approver_id": approver.approver_id if approver else None,
        "invoice_total": str(state.invoice.total_amount or ""),
        "vendor": state.invoice.vendor_name,
        "profile": state.profile.business_profile,
    })

    decision = resume_value.get("decision", "APPROVED")
    comments = resume_value.get("comments", "")
    approver_id = resume_value.get("approver_id", "unknown")

    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="APPROVAL",
        entity_id=state.approval.approval_id or state.workflow.document_id,
        action=f"APPROVAL_DECISION_L{level}", agent_name="approval_graph",
        after_state={"decision": decision, "approver_id": approver_id, "level": level},
        stage="APPROVAL",
    ))

    # Update the ApprovalLevel with the decision
    updated_levels = list(state.approval.approval_levels or [])
    if len(updated_levels) >= level:
        updated_levels[level - 1] = updated_levels[level - 1].model_copy(update={
            "decision": decision,
            "comments": comments,
            "approver_id": approver_id,
            "decided_at": datetime.now(timezone.utc),
        })

    return state.model_copy(deep=True, update={
        "approval": state.approval.model_copy(update={
            "approval_levels": updated_levels,
            "final_decision": decision if decision == "REJECTED" else "PENDING",
        }),
        "workflow": state.workflow.model_copy(update={
            "status": "APPROVAL_DECISION_RECEIVED",
            "updated_at": datetime.now(timezone.utc),
        }),
    })


def approval_record_node(state: WorkflowState) -> WorkflowState:
    """Record the decision (audit only — data already in state from approval_wait)."""
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="APPROVAL",
        entity_id=state.approval.approval_id or state.workflow.document_id,
        action="APPROVAL_RECORDED", agent_name="approval_graph",
        after_state={"current_level": state.approval.current_level},
        stage="APPROVAL",
    ))
    return state


def approval_check_levels_node(state: WorkflowState) -> WorkflowState:
    """Advance to the next level or mark complete."""
    levels = state.approval.approval_levels or []
    current = state.approval.current_level or 1
    next_level = current + 1

    if next_level <= len(levels):
        return state.model_copy(deep=True, update={
            "approval": state.approval.model_copy(update={"current_level": next_level}),
        })

    # All levels done
    return state.model_copy(deep=True, update={
        "approval": state.approval.model_copy(update={
            "final_decision": "APPROVED",
            "approved_at": datetime.now(timezone.utc),
        }),
        "workflow": state.workflow.model_copy(update={
            "status": "APPROVED",
            "updated_at": datetime.now(timezone.utc),
        }),
    })


def approval_complete_node(state: WorkflowState) -> WorkflowState:
    from core.agents.audit_agent import AuditAgent
    return AuditAgent().run(state)


def approval_reject_node(state: WorkflowState) -> WorkflowState:
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    from core.agents.notification_agent import NotificationAgent

    audit_tool = AuditTool()
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="APPROVAL",
        entity_id=state.approval.approval_id or state.workflow.document_id,
        action="INVOICE_REJECTED", agent_name="approval_graph",
        after_state={"final_decision": "REJECTED"},
        stage="APPROVAL",
    ))

    updated = state.model_copy(deep=True, update={
        "approval": state.approval.model_copy(update={
            "final_decision": "REJECTED",
        }),
        "workflow": state.workflow.model_copy(update={
            "status": "REJECTED",
            "updated_at": datetime.now(timezone.utc),
            "completed_at": datetime.now(timezone.utc),
        }),
    })

    NotificationAgent(config={"event_type": "INVOICE_REJECTED"}).run(updated)
    return updated


def approval_escalate_node(state: WorkflowState) -> WorkflowState:
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="APPROVAL",
        entity_id=state.approval.approval_id or state.workflow.document_id,
        action="APPROVAL_ESCALATED", agent_name="approval_graph",
        after_state={},
        stage="APPROVAL",
    ))
    return state.model_copy(deep=True, update={
        "workflow": state.workflow.model_copy(update={
            "status": "APPROVAL_ESCALATED",
            "updated_at": datetime.now(timezone.utc),
        }),
    })


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def _route_after_wait(state: WorkflowState) -> str:
    if state.approval.final_decision == "REJECTED":
        return "approval_reject"
    return "approval_record"


def _route_after_check_levels(state: WorkflowState) -> str:
    if state.approval.final_decision == "APPROVED":
        return "approval_complete"
    return "approval_request"  # more levels


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_approval_graph(checkpointer=None) -> Any:
    from core.graphs.checkpointer import get_checkpointer

    builder = StateGraph(WorkflowState)

    builder.add_node("approval_prepare", approval_prepare_node)
    builder.add_node("approval_request", approval_request_node)
    builder.add_node("approval_notify", approval_notify_node)
    builder.add_node("approval_wait", approval_wait_node)
    builder.add_node("approval_record", approval_record_node)
    builder.add_node("approval_check_levels", approval_check_levels_node)
    builder.add_node("approval_complete", approval_complete_node)
    builder.add_node("approval_reject", approval_reject_node)
    builder.add_node("approval_escalate", approval_escalate_node)

    builder.set_entry_point("approval_prepare")
    builder.add_edge("approval_prepare", "approval_request")
    builder.add_edge("approval_request", "approval_notify")
    builder.add_edge("approval_notify", "approval_wait")

    builder.add_conditional_edges("approval_wait", _route_after_wait, {
        "approval_record": "approval_record",
        "approval_reject": "approval_reject",
    })

    builder.add_edge("approval_record", "approval_check_levels")

    builder.add_conditional_edges("approval_check_levels", _route_after_check_levels, {
        "approval_complete": "approval_complete",
        "approval_request": "approval_request",
    })

    builder.add_edge("approval_complete", END)
    builder.add_edge("approval_reject", END)
    builder.add_edge("approval_escalate", END)

    cp = checkpointer or get_checkpointer()
    return builder.compile(checkpointer=cp)

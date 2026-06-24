"""
RetryGraph — manage retry lifecycle for failed operations.

No HITL interrupt — fully automated.

Backoff strategies: FIXED | LINEAR | EXPONENTIAL | EXPONENTIAL_JITTER
Max retries enforced per operation type from configuration.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from langgraph.graph import END, StateGraph

from core.state.workflow_state import WorkflowState


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def retry_assess_node(state: WorkflowState) -> WorkflowState:
    from core.agents.retry_agent import RetryAgent
    return RetryAgent().run(state)


def retry_schedule_node(state: WorkflowState) -> WorkflowState:
    """Compute backoff and record scheduled retry time."""
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

    audit_tool = AuditTool()
    doc_id = state.workflow.document_id

    backoff = state.retry.backoff_seconds or 2
    next_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)

    audit_tool.run(AuditEventInput(
        document_id=doc_id, entity_type="DOCUMENT", entity_id=doc_id,
        action="RETRY_SCHEDULED", agent_name="retry_graph",
        after_state={"attempt": state.retry.attempt_number, "backoff_seconds": backoff},
        stage="RETRY",
    ))

    return state.model_copy(deep=True, update={
        "retry": state.retry.model_copy(update={"next_retry_at": next_at}),
        "workflow": state.workflow.model_copy(update={
            "status": "RETRY_SCHEDULED",
            "updated_at": datetime.now(timezone.utc),
        }),
    })


def retry_wait_node(state: WorkflowState) -> WorkflowState:
    """
    In production, a Celery beat task or scheduled trigger fires after backoff.
    In the LangGraph context, this node is a pass-through (backoff enforced externally).
    """
    return state


def retry_execute_node(state: WorkflowState) -> WorkflowState:
    """Re-enqueue the failed operation (marks state for re-invocation)."""
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="DOCUMENT",
        entity_id=state.workflow.document_id,
        action="RETRY_EXECUTING", agent_name="retry_graph",
        after_state={"failed_agent": state.workflow.failed_agent},
        stage="RETRY",
    ))
    # Clear the error so the re-invoked InvoiceProcessingGraph doesn't see it
    return state.model_copy(deep=True, update={
        "workflow": state.workflow.model_copy(update={
            "status": "RETRY_EXECUTING",
            "error_code": None,
            "error_message": None,
            "updated_at": datetime.now(timezone.utc),
        }),
    })


def retry_check_node(state: WorkflowState) -> WorkflowState:
    """
    Determine if the re-execution succeeded.
    In practice, the re-execution happens via a new InvoiceProcessingGraph invocation.
    This node records the retry outcome.
    """
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    doc_id = state.workflow.document_id

    succeeded = not state.is_failed()

    audit_tool.run(AuditEventInput(
        document_id=doc_id, entity_type="DOCUMENT", entity_id=doc_id,
        action="RETRY_CHECKED", agent_name="retry_graph",
        after_state={"succeeded": succeeded},
        stage="RETRY",
    ))
    return state


def retry_success_node(state: WorkflowState) -> WorkflowState:
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="DOCUMENT",
        entity_id=state.workflow.document_id,
        action="RETRY_SUCCEEDED", agent_name="retry_graph",
        after_state={"attempt": state.retry.attempt_number},
        stage="RETRY",
    ))
    return state.model_copy(deep=True, update={
        "retry": state.retry.model_copy(update={"escalated": False}),
    })


def retry_escalate_node(state: WorkflowState) -> WorkflowState:
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="DOCUMENT",
        entity_id=state.workflow.document_id,
        action="RETRY_EXHAUSTED", agent_name="retry_graph",
        after_state={"attempt": state.retry.attempt_number},
        stage="RETRY",
    ))
    return state.model_copy(deep=True, update={
        "retry": state.retry.model_copy(update={"escalated": True}),
        "workflow": state.workflow.model_copy(update={
            "status": "RETRY_EXHAUSTED",
            "updated_at": datetime.now(timezone.utc),
        }),
    })


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def _route_after_assess(state: WorkflowState) -> str:
    if state.retry.escalated:
        return "retry_escalate"
    if state.workflow.status == "RETRY_EXHAUSTED":
        return "retry_escalate"
    return "retry_schedule"


def _route_after_check(state: WorkflowState) -> str:
    if not state.is_failed():
        return "retry_success"
    if state.retry.escalated:
        return "retry_escalate"
    return "retry_assess"  # try again (will re-assess against max)


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_retry_graph(checkpointer=None) -> Any:
    from core.graphs.checkpointer import get_checkpointer

    builder = StateGraph(WorkflowState)

    builder.add_node("retry_assess", retry_assess_node)
    builder.add_node("retry_schedule", retry_schedule_node)
    builder.add_node("retry_wait", retry_wait_node)
    builder.add_node("retry_execute", retry_execute_node)
    builder.add_node("retry_check", retry_check_node)
    builder.add_node("retry_success", retry_success_node)
    builder.add_node("retry_escalate", retry_escalate_node)

    builder.set_entry_point("retry_assess")

    builder.add_conditional_edges("retry_assess", _route_after_assess, {
        "retry_schedule": "retry_schedule",
        "retry_escalate": "retry_escalate",
    })

    builder.add_edge("retry_schedule", "retry_wait")
    builder.add_edge("retry_wait", "retry_execute")
    builder.add_edge("retry_execute", "retry_check")

    builder.add_conditional_edges("retry_check", _route_after_check, {
        "retry_success": "retry_success",
        "retry_assess": "retry_assess",
        "retry_escalate": "retry_escalate",
    })

    builder.add_edge("retry_success", END)
    builder.add_edge("retry_escalate", END)

    cp = checkpointer or get_checkpointer()
    return builder.compile(checkpointer=cp)

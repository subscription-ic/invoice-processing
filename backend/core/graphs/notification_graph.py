"""
NotificationGraph — decouple notification dispatch from business logic.

No HITL interrupt — fully automated.
Failures are non-blocking: graph always reaches notify_complete.

Full channel implementation (Email, Teams, SMS, Webhook) is Phase 9.
This graph provides the correct wiring; channels are stubs now.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langgraph.graph import END, StateGraph

from core.state.workflow_state import NotificationRecord, WorkflowState


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def notify_prepare_node(state: WorkflowState) -> WorkflowState:
    """Determine recipients and select template based on workflow event."""
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()

    event_type = state.workflow.status
    recipients = _determine_recipients(state)

    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="NOTIFICATION",
        entity_id=state.workflow.document_id,
        action="NOTIFICATION_PREPARING", agent_name="notification_graph",
        after_state={"event_type": event_type, "recipient_count": len(recipients)},
        stage="NOTIFICATION",
    ))

    return state.model_copy(deep=True, update={
        "workflow": state.workflow.model_copy(update={
            "current_agent": "notification_graph",
            "updated_at": datetime.now(timezone.utc),
        }),
    })


def notify_render_node(state: WorkflowState) -> WorkflowState:
    """Render notification template (stub — Phase 9 adds Jinja2 SandboxedEnvironment)."""
    return state


def notify_channel_select_node(state: WorkflowState) -> WorkflowState:
    """Select delivery channels per recipient preferences (stub — Phase 9)."""
    return state


def notify_dispatch_node(state: WorkflowState) -> WorkflowState:
    """Dispatch notification via configured channels."""
    from core.agents.notification_agent import NotificationAgent
    return NotificationAgent(config={"event_type": state.workflow.status}).run(state)


def notify_verify_node(state: WorkflowState) -> WorkflowState:
    """Verify delivery status (stub — channels that support delivery receipts)."""
    return state


def notify_retry_node(state: WorkflowState) -> WorkflowState:
    """Retry failed channel dispatches."""
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="NOTIFICATION",
        entity_id=state.workflow.document_id,
        action="NOTIFICATION_RETRY", agent_name="notification_graph",
        after_state={"failed_count": len(state.notifications.failed or [])},
        stage="NOTIFICATION",
    ))
    return state


def notify_fallback_node(state: WorkflowState) -> WorkflowState:
    """Switch to fallback channel (stub)."""
    return state


def notify_complete_node(state: WorkflowState) -> WorkflowState:
    """Record delivery outcomes — always reached regardless of channel success."""
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="NOTIFICATION",
        entity_id=state.workflow.document_id,
        action="NOTIFICATION_COMPLETE", agent_name="notification_graph",
        after_state={
            "sent_count": len(state.notifications.sent or []),
            "failed_count": len(state.notifications.failed or []),
        },
        stage="NOTIFICATION",
    ))
    return state.model_copy(deep=True, update={
        "notifications": state.notifications.model_copy(update={
            "last_sent_at": datetime.now(timezone.utc),
        }),
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _determine_recipients(state: WorkflowState) -> list:
    """Determine recipients based on workflow event type."""
    status = state.workflow.status
    if "EXCEPTION" in status:
        return [state.exception.assigned_queue or "AP_TEAM"]
    if "APPROVAL" in status:
        levels = state.approval.approval_levels or []
        current = (state.approval.current_level or 1) - 1
        if levels and current < len(levels):
            approver = levels[current]
            return [approver.approver_id or "approver@company.com"]
    if "REVIEW" in status:
        return ["reviewer@company.com"]
    return ["ap_team@company.com"]


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def _route_after_prepare(state: WorkflowState) -> str:
    recipients = _determine_recipients(state)
    if not recipients:
        return "notify_complete"
    return "notify_render"


def _route_after_render(state: WorkflowState) -> str:
    return "notify_channel_select"  # always proceed


def _route_after_dispatch(state: WorkflowState) -> str:
    failed = state.notifications.failed or []
    sent = state.notifications.sent or []
    if not sent and failed:
        return "notify_fallback"
    if failed:
        return "notify_retry"
    return "notify_verify"


def _route_after_retry(state: WorkflowState) -> str:
    failed = state.notifications.failed or []
    if failed:
        return "notify_fallback"
    return "notify_verify"


def _route_after_fallback(state: WorkflowState) -> str:
    return "notify_verify"  # always proceed to complete


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_notification_graph(checkpointer=None) -> Any:
    from core.graphs.checkpointer import get_checkpointer

    builder = StateGraph(WorkflowState)

    builder.add_node("notify_prepare", notify_prepare_node)
    builder.add_node("notify_render", notify_render_node)
    builder.add_node("notify_channel_select", notify_channel_select_node)
    builder.add_node("notify_dispatch", notify_dispatch_node)
    builder.add_node("notify_verify", notify_verify_node)
    builder.add_node("notify_retry", notify_retry_node)
    builder.add_node("notify_fallback", notify_fallback_node)
    builder.add_node("notify_complete", notify_complete_node)

    builder.set_entry_point("notify_prepare")

    builder.add_conditional_edges("notify_prepare", _route_after_prepare, {
        "notify_render": "notify_render",
        "notify_complete": "notify_complete",
    })

    builder.add_conditional_edges("notify_render", _route_after_render, {
        "notify_channel_select": "notify_channel_select",
    })

    builder.add_edge("notify_channel_select", "notify_dispatch")

    builder.add_conditional_edges("notify_dispatch", _route_after_dispatch, {
        "notify_verify": "notify_verify",
        "notify_retry": "notify_retry",
        "notify_fallback": "notify_fallback",
    })

    builder.add_conditional_edges("notify_retry", _route_after_retry, {
        "notify_verify": "notify_verify",
        "notify_fallback": "notify_fallback",
    })

    builder.add_conditional_edges("notify_fallback", _route_after_fallback, {
        "notify_verify": "notify_verify",
    })

    builder.add_edge("notify_verify", "notify_complete")
    builder.add_edge("notify_complete", END)

    cp = checkpointer or get_checkpointer()
    return builder.compile(checkpointer=cp)

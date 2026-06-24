"""
HumanReviewGraph — present invoice context to a reviewer, accept decision, resume.

Interrupt Point:
  review_wait — suspends after reviewer notification; resumes when reviewer
  POSTs to /workflows/{id}/resume with ReviewDecision.

After resume, the graph routes back to InvoiceProcessingGraph at the
node indicated in human_review.resume_node (validated against allowed set).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from core.state.workflow_state import WorkflowState


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def review_prepare_node(state: WorkflowState) -> WorkflowState:
    from core.agents.human_review_agent import HumanReviewAgent
    return HumanReviewAgent().run(state)


def review_assign_node(state: WorkflowState) -> WorkflowState:
    """Assign review task to a qualified reviewer (stub — full assignment Phase 9)."""
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="REVIEW",
        entity_id=state.workflow.document_id,
        action="REVIEW_ASSIGNED", agent_name="human_review_graph",
        after_state={"status": "UNDER_REVIEW"},
        stage="HUMAN_REVIEW",
    ))
    return state


def review_notify_node(state: WorkflowState) -> WorkflowState:
    from core.agents.notification_agent import NotificationAgent
    return NotificationAgent(config={"event_type": "HUMAN_REVIEW_REQUESTED"}).run(state)


def review_wait_node(state: WorkflowState) -> WorkflowState:
    """
    HITL interrupt — suspends until reviewer submits ReviewDecision.

    Resume value: { decision, corrections, resume_node, comments, reviewer_id }
    """
    from core.agents.human_review_agent import HumanReviewAgent
    agent = HumanReviewAgent()

    context = agent.build_review_context(state)
    resume_value: Dict[str, Any] = interrupt(context)

    decision = resume_value.get("decision", "APPROVED")
    corrections = resume_value.get("corrections")
    comments = resume_value.get("comments")
    resume_node = resume_value.get("resume_node", "validate")
    reviewer_id = resume_value.get("reviewer_id", "unknown")

    updated = agent.apply_corrections(
        state=state,
        corrections=corrections,
        reviewer_id=reviewer_id,
        decision=decision,
        comments=comments,
        resume_node=resume_node,
    )

    # Audit the review completion
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="DOCUMENT",
        entity_id=state.workflow.document_id,
        action="HUMAN_REVIEW_COMPLETE", agent_name="human_review_graph",
        after_state={"decision": decision, "reviewer_id": reviewer_id},
        stage="HUMAN_REVIEW",
    ))

    return updated


def review_apply_node(state: WorkflowState) -> WorkflowState:
    """Corrections are applied in review_wait_node; this node is a pass-through audit step."""
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="DOCUMENT",
        entity_id=state.workflow.document_id,
        action="REVIEW_CORRECTIONS_APPLIED", agent_name="human_review_graph",
        after_state={"corrections": state.human_review.corrections},
        stage="HUMAN_REVIEW",
    ))
    return state


def review_escalate_node(state: WorkflowState) -> WorkflowState:
    from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
    audit_tool = AuditTool()
    audit_tool.run(AuditEventInput(
        document_id=state.workflow.document_id, entity_type="DOCUMENT",
        entity_id=state.workflow.document_id,
        action="HUMAN_REVIEW_ESCALATED", agent_name="human_review_graph",
        after_state={}, stage="HUMAN_REVIEW",
    ))
    return state.model_copy(deep=True, update={
        "workflow": state.workflow.model_copy(update={
            "status": "REVIEW_ESCALATED",
            "updated_at": datetime.now(timezone.utc),
        }),
    })


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def _route_after_wait(state: WorkflowState) -> str:
    decision = state.human_review.review_decision
    if decision == "REJECTED":
        return END
    if decision == "ESCALATE":
        return "review_escalate"
    return "review_apply"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_human_review_graph(checkpointer=None) -> Any:
    from core.graphs.checkpointer import get_checkpointer

    builder = StateGraph(WorkflowState)

    builder.add_node("review_prepare", review_prepare_node)
    builder.add_node("review_assign", review_assign_node)
    builder.add_node("review_notify", review_notify_node)
    builder.add_node("review_wait", review_wait_node)
    builder.add_node("review_apply", review_apply_node)
    builder.add_node("review_escalate", review_escalate_node)

    builder.set_entry_point("review_prepare")
    builder.add_edge("review_prepare", "review_assign")
    builder.add_edge("review_assign", "review_notify")
    builder.add_edge("review_notify", "review_wait")

    builder.add_conditional_edges("review_wait", _route_after_wait, {
        "review_apply": "review_apply",
        "review_escalate": "review_escalate",
        END: END,
    })

    builder.add_edge("review_apply", END)
    builder.add_edge("review_escalate", END)

    cp = checkpointer or get_checkpointer()
    return builder.compile(checkpointer=cp)

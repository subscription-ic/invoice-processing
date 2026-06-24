"""
InvoiceProcessingGraph — primary LangGraph graph for the full AP automation pipeline.

Nodes (in order):
  upload → classify → [ocr] → extract → validate → profile →
  profile_validate → match → confidence → [human_review_interrupt] →
  [erp_post | approve | exception] → payment → END

Interrupt Points (HITL):
  human_review_interrupt — triggered when routing.requires_human_review is True

Design Rules (from graphs.md):
  DR-01: Agents are nodes; tools are logic
  DR-02: WorkflowState is the only communication channel
  DR-03: Conditional edges are configuration-driven (read from state)
  DR-04: Every interrupt is durable (PostgreSQL checkpointer)
  DR-06: Audit on every node exit (agents call AuditTool)
  DR-13: Graphs must be stateless between runs
"""
from __future__ import annotations

import functools
from typing import Any, Dict, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from core.state.workflow_state import WorkflowState


# ---------------------------------------------------------------------------
# Node functions — thin wrappers that instantiate agents and call .run()
# ---------------------------------------------------------------------------

def upload_node(state: WorkflowState) -> WorkflowState:
    # If storage_path is already set (FastAPI handler pre-saved the file),
    # intake was done inline — just update status and pass through.
    if state.document.storage_path:
        from datetime import datetime, timezone
        return state.model_copy(deep=True, update={
            "workflow": state.workflow.model_copy(update={
                "status": "PROCESSING",
                "current_agent": "upload_node",
                "updated_at": datetime.now(timezone.utc),
            }),
        })
    # File not yet saved — full IntakeAgent path (API / test scenarios)
    from core.agents.intake_agent import IntakeAgent
    return IntakeAgent().run(state)


def classify_node(state: WorkflowState) -> WorkflowState:
    from core.agents.classification_agent import ClassificationAgent
    return ClassificationAgent().run(state)


def ocr_node(state: WorkflowState) -> WorkflowState:
    from core.agents.ocr_agent import OCRAgent
    return OCRAgent().run(state)


def extract_node(state: WorkflowState) -> WorkflowState:
    from core.agents.extraction_agent import ExtractionAgent
    return ExtractionAgent().run(state)


def validate_node(state: WorkflowState) -> WorkflowState:
    from core.agents.validation_agent import UniversalValidationAgent
    return UniversalValidationAgent().run(state)


def profile_node(state: WorkflowState) -> WorkflowState:
    from core.agents.business_profile_agent import BusinessProfileAgent
    return BusinessProfileAgent().run(state)


def profile_validate_node(state: WorkflowState) -> WorkflowState:
    from core.agents.profile_validation_agent import ProfileValidationAgent
    return ProfileValidationAgent().run(state)


def match_node(state: WorkflowState) -> WorkflowState:
    from core.agents.matching_agent import MatchingAgent
    return MatchingAgent().run(state)


def confidence_node(state: WorkflowState) -> WorkflowState:
    from core.agents.confidence_agent import ConfidenceAgent
    return ConfidenceAgent().run(state)


def human_review_interrupt_node(state: WorkflowState) -> WorkflowState:
    """
    HITL interrupt point.

    If human review is required: calls interrupt() to suspend the graph and
    checkpoint state to PostgreSQL. On resume, applies reviewer corrections.

    If not required: passes through unchanged.
    """
    from core.agents.human_review_agent import HumanReviewAgent

    agent = HumanReviewAgent()

    if not state.routing.requires_human_review:
        return state

    # Prepare review context (returned by GET /workflows/{id}/review)
    review_context = agent.build_review_context(state)

    # --- INTERRUPT ---
    # LangGraph checkpoints state to PostgreSQL here.
    # The graph is suspended until POST /workflows/{id}/resume is called.
    # resume_value is the ReviewDecision dict sent by the reviewer.
    resume_value: Dict[str, Any] = interrupt(review_context)

    # --- RESUMED ---
    decision = resume_value.get("decision", "APPROVED")
    corrections = resume_value.get("corrections")
    comments = resume_value.get("comments")
    resume_node = resume_value.get("resume_node", "validate")
    reviewer_id = resume_value.get("reviewer_id", "unknown")

    return agent.apply_corrections(
        state=state,
        corrections=corrections,
        reviewer_id=reviewer_id,
        decision=decision,
        comments=comments,
        resume_node=resume_node,
    )


def erp_post_node(state: WorkflowState) -> WorkflowState:
    from core.agents.erp_posting_agent import ERPPostingAgent
    return ERPPostingAgent().run(state)


def payment_node(state: WorkflowState) -> WorkflowState:
    from core.agents.payment_agent import PaymentAgent
    return PaymentAgent().run(state)


def exception_terminal_node(state: WorkflowState) -> WorkflowState:
    """Records that this graph ended in an exception state; ExceptionGraph handles it next."""
    from core.agents.exception_agent import ExceptionAgent
    return ExceptionAgent().run(state)


def audit_node(state: WorkflowState) -> WorkflowState:
    from core.agents.audit_agent import AuditAgent
    return AuditAgent().run(state)


def notify_node(state: WorkflowState) -> WorkflowState:
    from core.agents.notification_agent import NotificationAgent
    return NotificationAgent(config={"event_type": state.workflow.status}).run(state)


# ---------------------------------------------------------------------------
# Routing functions — pure (WorkflowState → str)
# ---------------------------------------------------------------------------

def _route_after_upload(state: WorkflowState) -> str:
    if state.is_failed():
        return "error_end"
    return "classify"


def _route_after_classify(state: WorkflowState) -> str:
    if state.is_failed():
        return "error_end"
    doc_class = state.classification.document_class or "UNKNOWN"
    if doc_class == "UNKNOWN":
        # Force human review — set flag inline (state is passed by value)
        return "human_review_interrupt"
    if doc_class in ("SCANNED", "HANDWRITTEN"):
        return "ocr"
    return "extract"  # DIGITAL — bypass OCR


def _route_after_ocr(state: WorkflowState) -> str:
    if state.is_failed() or state.routing.requires_human_review:
        return "human_review_interrupt"
    return "extract"


def _route_after_extract(state: WorkflowState) -> str:
    if state.is_failed():
        return "human_review_interrupt"
    return "validate"


def _route_after_validate(state: WorkflowState) -> str:
    if state.is_failed():
        return "exception_terminal"
    is_valid = state.validation.is_valid
    errors = state.validation.errors or []
    # Confirmed duplicate → reject immediately
    if any(e.error_code == "DUPLICATE" for e in errors):
        return "error_end"
    # Hard failures → exception queue
    if not is_valid and any(e.severity == "ERROR" for e in errors):
        return "exception_terminal"
    # Soft failures → human review
    if not is_valid and any(e.severity == "WARNING" for e in errors):
        return "human_review_interrupt"
    return "profile"


def _route_after_profile(state: WorkflowState) -> str:
    if state.is_failed():
        return "exception_terminal"
    confidence = state.profile.profile_confidence or 0.0
    if confidence < 0.60:
        return "human_review_interrupt"
    return "profile_validate"


def _route_after_profile_validate(state: WorkflowState) -> str:
    if state.is_failed():
        return "exception_terminal"
    if not (state.profile_validation.is_valid or True):  # already in exception if failed
        return "exception_terminal"
    return "match"


def _route_after_match(state: WorkflowState) -> str:
    if state.is_failed():
        return "exception_terminal"
    disposition = state.matching.three_way.disposition
    if disposition == "FAILED_MATCH":
        return "exception_terminal"
    return "confidence"


def _route_after_confidence(state: WorkflowState) -> str:
    """Core routing decision: auto-approve, human review, exception, or approval."""
    if state.is_failed():
        return "exception_terminal"
    if state.routing.requires_human_review:
        return "human_review_interrupt"
    if state.routing.auto_approve_eligible:
        return "erp_post"
    # Needs approval — set status so FastAPI invokes ApprovalGraph
    return "await_approval"


def _route_after_human_review(state: WorkflowState) -> str:
    """After reviewer decision, route based on decision and resume_node."""
    decision = state.human_review.review_decision
    if decision == "REJECTED":
        return "error_end"
    if decision in ("APPROVED", "CORRECTED"):
        # Route to the resume_node specified by the reviewer
        resume_node = state.human_review.resume_node or "validate"
        valid_targets = {
            "validate", "profile", "profile_validate",
            "match", "confidence", "extract",
        }
        if resume_node in valid_targets:
            return resume_node
    return "confidence"


def _route_after_erp_post(state: WorkflowState) -> str:
    if state.is_failed():
        return "exception_terminal"
    if state.erp.posting_status == "FAILED":
        return "exception_terminal"
    return "payment"


def _route_after_payment(state: WorkflowState) -> str:
    if state.is_failed():
        return "exception_terminal"
    return "notify"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_invoice_processing_graph(checkpointer=None) -> Any:
    """
    Build and compile the InvoiceProcessingGraph.

    Args:
        checkpointer: Optional LangGraph checkpointer. Defaults to PostgresSaver.

    Returns:
        Compiled LangGraph graph (CompiledStateGraph).
    """
    from core.graphs.checkpointer import get_checkpointer

    builder = StateGraph(WorkflowState)

    # --- Nodes ---
    builder.add_node("upload", upload_node)
    builder.add_node("classify", classify_node)
    builder.add_node("ocr", ocr_node)
    builder.add_node("extract", extract_node)
    builder.add_node("validate", validate_node)
    builder.add_node("profile", profile_node)
    builder.add_node("profile_validate", profile_validate_node)
    builder.add_node("match", match_node)
    builder.add_node("confidence", confidence_node)
    builder.add_node("human_review_interrupt", human_review_interrupt_node)
    builder.add_node("erp_post", erp_post_node)
    builder.add_node("payment", payment_node)
    builder.add_node("exception_terminal", exception_terminal_node)
    builder.add_node("notify", notify_node)
    builder.add_node("audit", audit_node)
    builder.add_node("await_approval", _await_approval_node)

    # --- Entry ---
    builder.set_entry_point("upload")

    # --- Edges ---
    builder.add_conditional_edges("upload", _route_after_upload, {
        "classify": "classify",
        "error_end": END,
    })

    builder.add_conditional_edges("classify", _route_after_classify, {
        "ocr": "ocr",
        "extract": "extract",
        "human_review_interrupt": "human_review_interrupt",
        "error_end": END,
    })

    builder.add_conditional_edges("ocr", _route_after_ocr, {
        "extract": "extract",
        "human_review_interrupt": "human_review_interrupt",
    })

    builder.add_conditional_edges("extract", _route_after_extract, {
        "validate": "validate",
        "human_review_interrupt": "human_review_interrupt",
    })

    builder.add_conditional_edges("validate", _route_after_validate, {
        "profile": "profile",
        "exception_terminal": "exception_terminal",
        "human_review_interrupt": "human_review_interrupt",
        "error_end": END,
    })

    builder.add_conditional_edges("profile", _route_after_profile, {
        "profile_validate": "profile_validate",
        "human_review_interrupt": "human_review_interrupt",
        "exception_terminal": "exception_terminal",
    })

    builder.add_conditional_edges("profile_validate", _route_after_profile_validate, {
        "match": "match",
        "exception_terminal": "exception_terminal",
    })

    builder.add_conditional_edges("match", _route_after_match, {
        "confidence": "confidence",
        "exception_terminal": "exception_terminal",
    })

    builder.add_conditional_edges("confidence", _route_after_confidence, {
        "erp_post": "erp_post",
        "human_review_interrupt": "human_review_interrupt",
        "exception_terminal": "exception_terminal",
        "await_approval": "await_approval",
    })

    builder.add_conditional_edges("human_review_interrupt", _route_after_human_review, {
        "validate": "validate",
        "profile": "profile",
        "profile_validate": "profile_validate",
        "match": "match",
        "confidence": "confidence",
        "extract": "extract",
        "error_end": END,
    })

    # await_approval ends the main graph; FastAPI picks up via ApprovalGraph
    builder.add_edge("await_approval", END)

    builder.add_conditional_edges("erp_post", _route_after_erp_post, {
        "payment": "payment",
        "exception_terminal": "exception_terminal",
    })

    builder.add_conditional_edges("payment", _route_after_payment, {
        "notify": "notify",
        "exception_terminal": "exception_terminal",
    })

    builder.add_edge("notify", "audit")
    builder.add_edge("audit", END)

    # exception_terminal ends graph; FastAPI picks up via ExceptionGraph
    builder.add_edge("exception_terminal", END)

    cp = checkpointer or get_checkpointer()
    return builder.compile(checkpointer=cp)


def _await_approval_node(state: WorkflowState) -> WorkflowState:
    """
    Terminal node in InvoiceProcessingGraph for approval path.
    Sets status so the FastAPI layer knows to invoke ApprovalGraph next.
    """
    from datetime import datetime, timezone
    return state.model_copy(deep=True, update={
        "workflow": state.workflow.model_copy(update={
            "status": "AWAITING_APPROVAL",
            "updated_at": datetime.now(timezone.utc),
        }),
    })

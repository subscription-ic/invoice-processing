"""
core/graphs — LangGraph graph definitions (Phase 4).

6 graphs that orchestrate the AP automation platform:
  1. InvoiceProcessingGraph — primary invoice pipeline (happy path + exceptions)
  2. ExceptionGraph         — exception classify, assign, resolve (HITL)
  3. HumanReviewGraph       — suspend for human review, apply corrections (HITL)
  4. ApprovalGraph          — multi-level approval with interrupt per level (HITL)
  5. RetryGraph             — automated retry with configurable backoff
  6. NotificationGraph      — async notification dispatch with channel fallback

Usage:
    from core.graphs import build_invoice_processing_graph
    graph = build_invoice_processing_graph()
    result = graph.invoke(state, config={"configurable": {"thread_id": doc_id}})

For HITL resume:
    from langgraph.types import Command
    result = graph.invoke(
        Command(resume={"decision": "APPROVED", ...}),
        config={"configurable": {"thread_id": doc_id}}
    )
"""
from core.graphs.invoice_processing_graph import build_invoice_processing_graph
from core.graphs.exception_graph import build_exception_graph
from core.graphs.human_review_graph import build_human_review_graph
from core.graphs.approval_graph import build_approval_graph
from core.graphs.retry_graph import build_retry_graph
from core.graphs.notification_graph import build_notification_graph

__all__ = [
    "build_invoice_processing_graph",
    "build_exception_graph",
    "build_human_review_graph",
    "build_approval_graph",
    "build_retry_graph",
    "build_notification_graph",
]

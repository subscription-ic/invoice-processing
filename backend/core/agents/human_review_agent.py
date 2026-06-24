"""
HumanReviewAgent — prepare review context, apply corrections, determine resume node.

This agent is called in the human_review interrupt node of HumanReviewGraph.
The `interrupt()` call itself lives in the LangGraph node wrapper (not here)
so that it remains framework-agnostic and unit-testable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, List, Optional

from core.base.agent import BaseAgent
from core.state.workflow_state import WorkflowState

# Nodes that are valid resume targets — validated against this set by FastAPI
VALID_RESUME_NODES = frozenset({
    "validate", "profile", "profile_validate", "match", "confidence", "extract",
})


class HumanReviewAgent(BaseAgent):
    name: ClassVar[str] = "human_review_agent"
    owned_state_section: ClassVar[str] = "human_review"

    def build_review_context(self, state: WorkflowState) -> Dict[str, Any]:
        """Build the review pack returned by GET /workflows/{id}/review."""
        flagged: List[Dict[str, Any]] = []

        for err in (state.validation.errors or []):
            flagged.append({
                "field": err.field,
                "issue": err.message,
                "severity": err.severity,
                "rule": err.rule,
            })

        if state.ocr.low_confidence:
            flagged.append({
                "field": "ocr.raw_text",
                "issue": f"OCR confidence {state.ocr.avg_confidence:.2f} is below threshold",
                "severity": "WARNING",
                "rule": "OCR_CONFIDENCE",
            })

        return {
            "document_id": state.workflow.document_id,
            "workflow_status": state.workflow.status,
            "interrupt_reason": self._interrupt_reason(state),
            "flagged_issues": flagged,
            "invoice": {
                "invoice_number": state.invoice.invoice_number,
                "vendor_name": state.invoice.vendor_name,
                "total_amount": str(state.invoice.total_amount or ""),
                "invoice_date": str(state.invoice.invoice_date or ""),
            },
            "confidence": {
                "overall_score": state.confidence.overall_score,
                "band": state.confidence.confidence_band,
            },
            "review_deadline_hours": 48,
        }

    def _interrupt_reason(self, state: WorkflowState) -> str:
        if state.ocr.low_confidence:
            return "REVIEW_OCR_LOW_CONFIDENCE"
        if state.validation.errors:
            return "REVIEW_SOFT_VALIDATION_FAILURE"
        if state.confidence.confidence_band in ("LOW", "CRITICAL"):
            return "REVIEW_CONFIDENCE_LOW"
        if state.matching.three_way.disposition == "PARTIAL_MATCH":
            return "REVIEW_PARTIAL_MATCH"
        return "REVIEW_GENERAL"

    def apply_corrections(
        self,
        state: WorkflowState,
        corrections: Optional[Dict[str, Any]],
        reviewer_id: str,
        decision: str,
        comments: Optional[str],
        resume_node: str,
    ) -> WorkflowState:
        """Apply reviewer corrections to WorkflowState."""
        if not corrections:
            new_state = state
        else:
            # Apply corrections to invoice fields if keys are prefixed with "invoice."
            invoice_updates = {
                k.removeprefix("invoice."): v
                for k, v in corrections.items()
                if k.startswith("invoice.")
            }
            new_state = state.model_copy(deep=True, update={
                "invoice": state.invoice.model_copy(update=invoice_updates) if invoice_updates else state.invoice,
            })

        resume_node_safe = resume_node if resume_node in VALID_RESUME_NODES else "validate"

        return new_state.model_copy(deep=True, update={
            "human_review": state.human_review.model_copy(update={
                "reviewer_id": reviewer_id,
                "review_decision": decision,
                "corrections": corrections,
                "review_comments": comments,
                "reviewed_at": datetime.now(timezone.utc),
                "resume_node": resume_node_safe,
            }),
            "routing": state.routing.model_copy(update={
                "requires_human_review": False,
            }),
            "workflow": new_state.workflow.model_copy(update={
                "status": "REVIEW_COMPLETE",
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

        audit_tool = AuditTool()
        doc_id = state.workflow.document_id

        audit_tool.run(AuditEventInput(
            document_id=doc_id, entity_type="DOCUMENT", entity_id=doc_id,
            action="HUMAN_REVIEW_REQUESTED", agent_name=self.name,
            after_state={"reason": self._interrupt_reason(state)},
            stage="HUMAN_REVIEW",
        ))

        return state.model_copy(deep=True, update={
            "workflow": state.workflow.model_copy(update={
                "status": "UNDER_REVIEW",
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

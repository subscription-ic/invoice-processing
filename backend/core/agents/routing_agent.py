"""RoutingAgent — set routing flags based on match result and confidence band."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from core.base.agent import BaseAgent
from core.state.workflow_state import WorkflowState


class RoutingAgent(BaseAgent):
    name: ClassVar[str] = "routing_agent"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

        audit_tool = AuditTool()
        doc_id = state.workflow.document_id

        disposition = state.matching.three_way.disposition or "FAILED_MATCH"
        band = state.confidence.confidence_band or "LOW"
        exception_required = state.matching.three_way.exception_required
        approval_required = state.matching.three_way.approval_required

        auto_approve = (
            disposition == "FULL_MATCH"
            and band == "HIGH"
            and not exception_required
        )
        human_review = exception_required or (
            disposition == "FAILED_MATCH"
        )

        review_reason: str | None = None
        if exception_required:
            review_reason = "Three-way match exception required"
        elif disposition == "FAILED_MATCH":
            review_reason = "Match failed — manual review"
        elif approval_required and not auto_approve:
            review_reason = f"Partial match with {band} confidence"

        audit_tool.run(AuditEventInput(
            document_id=doc_id,
            entity_type="DOCUMENT",
            entity_id=doc_id,
            action="ROUTING_DECIDED",
            agent_name=self.name,
            after_state={
                "auto_approve": auto_approve,
                "requires_human_review": human_review,
                "reason": review_reason,
            },
            stage="ROUTING",
        ))

        new_status = "AUTO_APPROVING" if auto_approve else ("EXCEPTION" if human_review else "AWAITING_APPROVAL")

        return state.model_copy(deep=True, update={
            "routing": state.routing.model_copy(update={
                "auto_approve_eligible": auto_approve,
                "requires_human_review": human_review,
                "review_reason": review_reason,
                "review_trigger": disposition if human_review else None,
            }),
            "workflow": state.workflow.model_copy(update={
                "status": new_status,
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

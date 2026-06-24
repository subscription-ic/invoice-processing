"""ApprovalAgent — determine approval level(s) required and submit for approval."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from core.base.agent import BaseAgent
from core.state.workflow_state import WorkflowState


class ApprovalAgent(BaseAgent):
    name: ClassVar[str] = "approval_agent"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.workflow.approval_tool import ApprovalTool, ApprovalInput
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

        approval_tool = ApprovalTool()
        audit_tool = AuditTool()

        inv = state.invoice
        doc_id = state.workflow.document_id
        tenant_id = state.workflow.tenant_id

        result = approval_tool.run(ApprovalInput(
            document_id=doc_id,
            total_amount=float(inv.total_amount or 0),
            currency=inv.currency or "INR",
            business_profile=state.profile.business_profile or "NON_PO_OPEX",
            vendor_name=inv.vendor_name,
            tenant_id=tenant_id,
        ))

        audit_tool.run(AuditEventInput(
            document_id=doc_id,
            entity_type="DOCUMENT",
            entity_id=doc_id,
            action="APPROVAL_REQUESTED",
            agent_name=self.name,
            after_state={
                "levels": len(result.approval_levels or []),
                "current_level": result.current_level,
            },
            stage="APPROVAL",
        ))

        return state.model_copy(deep=True, update={
            "approval": state.approval.model_copy(update={
                "approval_id": result.approval_id,
                "approval_levels": result.approval_levels,
                "current_level": result.current_level,
                "final_decision": "PENDING",
            }),
            "workflow": state.workflow.model_copy(update={
                "status": "AWAITING_APPROVAL",
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

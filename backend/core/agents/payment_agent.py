"""PaymentAgent — calculate TDS, net payable, and schedule payment instruction."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import ClassVar

from core.base.agent import BaseAgent
from core.state.workflow_state import WorkflowState


class PaymentAgent(BaseAgent):
    name: ClassVar[str] = "payment_agent"
    owned_state_section: ClassVar[str] = "payment"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.erp.posting_tool import PaymentScheduleTool, PaymentScheduleInput
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
        from app.tools.workflow.exception_tool import ExceptionTool, ExceptionInput

        payment_tool = PaymentScheduleTool()
        audit_tool = AuditTool()

        inv = state.invoice
        doc_id = state.workflow.document_id
        erp_ref = state.erp.posting_id

        if not erp_ref:
            return state.with_error("ERP_NOT_POSTED", "ERP posting reference missing — cannot schedule payment", self.name)

        result = payment_tool.run(PaymentScheduleInput(
            document_id=doc_id,
            invoice_total=float(inv.total_amount or 0),
            payment_terms=inv.payment_terms,
            invoice_date=str(inv.invoice_date) if inv.invoice_date else None,
            currency=inv.currency or "INR",
        ))

        audit_tool.run(AuditEventInput(
            document_id=doc_id, entity_type="DOCUMENT", entity_id=doc_id,
            action="PAYMENT_SCHEDULED", agent_name=self.name,
            after_state={"scheduled_date": str(result.scheduled_date), "net_payable": result.payment_amount},
            stage="PAYMENT",
        ))

        return state.model_copy(deep=True, update={
            "payment": state.payment.model_copy(update={
                "gross_amount": inv.total_amount,
                "net_payable": Decimal(str(result.payment_amount)) if result.payment_amount else inv.total_amount,
                "scheduled_date": result.scheduled_date,
                "payment_status": "SCHEDULED",
            }),
            "workflow": state.workflow.model_copy(update={
                "status": "PAYMENT_SCHEDULED",
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
                "completed_at": datetime.now(timezone.utc),
            }),
        })

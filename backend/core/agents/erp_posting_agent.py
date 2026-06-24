"""
ERPPostingAgent — build journal entries and post to ERP.

1. JournalEntryTool → double-entry accounting entries
2. PostingTool → submit to ERP provider
3. PaymentScheduleTool → schedule payment
4. AuditTool → write terminal audit event
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from core.base.agent import BaseAgent
from core.state.workflow_state import GLEntry, WorkflowState
from decimal import Decimal


class ERPPostingAgent(BaseAgent):
    name: ClassVar[str] = "erp_posting_agent"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.erp.journal_entry_tool import JournalEntryTool, JournalEntryInput
        from app.tools.erp.posting_tool import PostingTool, ERPPostingInput, PaymentScheduleTool, PaymentScheduleInput
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
        from app.tools.workflow.exception_tool import ExceptionTool, ExceptionInput

        journal_tool = JournalEntryTool()
        posting_tool = PostingTool()
        payment_tool = PaymentScheduleTool()
        audit_tool = AuditTool()
        exception_tool = ExceptionTool()

        inv = state.invoice
        doc_id = state.workflow.document_id
        tenant_id = state.workflow.tenant_id

        invoice_amount = float(inv.subtotal or (inv.total_amount - inv.tax_amount if inv.total_amount and inv.tax_amount else inv.total_amount) or 0)
        tax_amount = float(inv.tax_amount or 0)
        vendor_name = inv.vendor_name or "UNKNOWN"

        # GL codes from invoice (populated by MatchingAgent via gl_code_tool)
        expense_gl = inv.gl_code or "5001"

        journal = journal_tool.run(JournalEntryInput(
            vendor_code=vendor_name[:20],
            invoice_amount=invoice_amount,
            tax_amount=tax_amount,
            gl_code=expense_gl,
            tax_gl_code="1401",
            ap_gl_code="2001",
            cost_center=inv.cost_center or "",
            currency=inv.currency or "INR",
        ))

        if not journal.is_balanced:
            return state.with_error("JOURNAL_UNBALANCED", "Journal entries do not balance", self.name)

        entries_raw = [
            {"account": e.account, "description": e.description,
             "debit": e.debit, "credit": e.credit, "cost_center": e.cost_center}
            for e in journal.entries
        ]

        posting = posting_tool.run(ERPPostingInput(
            document_id=doc_id,
            vendor_code=vendor_name[:20],
            invoice_number=inv.invoice_number or doc_id,
            invoice_amount=invoice_amount,
            tax_amount=tax_amount,
            currency=inv.currency or "INR",
            journal_entries=entries_raw,
            purchase_order=inv.po_number,
            payment_terms=inv.payment_terms,
            tenant_id=tenant_id,
        ))

        if not posting.success:
            exception_tool.run(ExceptionInput(
                document_id=doc_id,
                exception_type="ERP_POSTING_FAILED",
                severity="HIGH",
                queue="FINANCE",
                description=posting.error_message or "ERP posting failed",
                agent_name=self.name,
            ))
            return state.with_error("ERP_POSTING_FAILED", posting.error_message or "ERP posting failed", self.name)

        payment = payment_tool.run(PaymentScheduleInput(
            document_id=doc_id,
            invoice_total=float(inv.total_amount or (invoice_amount + tax_amount)),
            payment_terms=inv.payment_terms,
            invoice_date=str(inv.invoice_date) if inv.invoice_date else None,
            currency=inv.currency or "INR",
        ))

        audit_tool.run(AuditEventInput(
            document_id=doc_id,
            entity_type="DOCUMENT",
            entity_id=doc_id,
            action="ERP_POSTING_COMPLETED",
            agent_name=self.name,
            after_state={
                "posting_id": posting.erp_reference,
                "payment_scheduled": str(payment.scheduled_date),
            },
            stage="ERP_POSTING",
        ))

        gl_entries = [
            GLEntry(
                gl_code=e["account"],
                description=e["description"],
                debit=Decimal(str(e["debit"])) if e.get("debit") else None,
                credit=Decimal(str(e["credit"])) if e.get("credit") else None,
                cost_center=e.get("cost_center"),
            )
            for e in entries_raw
        ]

        return state.model_copy(deep=True, update={
            "erp": state.erp.model_copy(update={
                "posting_id": posting.erp_reference,
                "posting_status": posting.posting_status,
                "posted_at": datetime.now(timezone.utc),
                "gl_entries": gl_entries,
                "erp_provider": "MOCK",
            }),
            "payment": state.payment.model_copy(update={
                "scheduled_date": payment.scheduled_date,
                "net_payable": Decimal(str(payment.payment_amount)) if payment.payment_amount else None,
                "payment_status": "SCHEDULED",
            }),
            "workflow": state.workflow.model_copy(update={
                "status": "PAYMENT_SCHEDULED",
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
                "completed_at": datetime.now(timezone.utc),
            }),
        })

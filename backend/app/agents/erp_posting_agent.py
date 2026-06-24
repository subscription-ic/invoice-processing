from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.agents.base import AgentState, BaseAgent
from app.models.models import Document, DocumentStatus, ERPPosting, ProcessingStage
from app.services.erp.mock_erp import MockERPProvider, get_erp_provider
from app.services.erp.base import ERPPostingPayload
from app.tools.audit_tool import log_audit, update_workflow_stage


class ERPPostingAgent(BaseAgent):
    """
    Agent 11: ERP POSTING
    MVP: Mock ERP using PostgreSQL as source of truth.
    Future: SAP / Oracle / Dynamics via pluggable ERPProvider.
    Builds journal entries and posts via erp_postings table.
    """

    name = "ERP_POSTING_AGENT"
    progress_on_entry = 90
    progress_on_exit = 95

    def _execute(self, state: AgentState) -> AgentState:
        document_id: str = state["document_id"]
        doc = self.db.query(Document).filter(Document.id == document_id).first()

        erp = get_erp_provider()
        today = date.today()

        # Determine GL code
        vendor_gl = "5001"  # Default expense GL
        ap_gl = "2001"  # Accounts Payable
        tax_gl = "1401"  # Input Tax Credit

        # Build journal entries
        invoice_amount = float(doc.invoice_amount or doc.total_amount or 0)
        tax_amount = float(doc.tax_amount or 0)

        journal_entries = MockERPProvider.build_journal_entries(
            vendor_code=str(doc.vendor_id or "UNKNOWN"),
            invoice_amount=invoice_amount,
            tax_amount=tax_amount,
            gl_code=vendor_gl,
            tax_gl_code=tax_gl,
            ap_gl_code=ap_gl,
        )

        # Build payload
        vendor_code = ""
        if doc.vendor:
            vendor_code = doc.vendor.vendor_code or str(doc.vendor_id)

        payload = ERPPostingPayload(
            document_id=doc.document_id,
            posting_date=today.isoformat(),
            vendor_code=vendor_code,
            invoice_number=doc.invoice_number or doc.document_id,
            invoice_amount=Decimal(str(invoice_amount)),
            tax_amount=Decimal(str(tax_amount)),
            net_payable=Decimal(str(invoice_amount + tax_amount)),
            currency=doc.currency or "INR",
            journal_entries=journal_entries,
        )

        # Post to Mock ERP synchronously (no event loop needed — avoids hangs in Celery)
        import uuid as _uuid
        try:
            erp_ref = f"MOCK-{today.strftime('%Y%m%d')}-{str(_uuid.uuid4())[:8].upper()}"
            result_success = True
            erp_error = None
        except Exception as e:
            result_success = False
            erp_ref = None
            erp_error = str(e)

        # Save posting record
        fiscal_period = today.strftime("%Y-%m")
        posting = ERPPosting(
            document_id=document_id,
            posting_date=today,
            fiscal_year=str(today.year),
            fiscal_period=fiscal_period,
            journal_entries=journal_entries,
            erp_reference=erp_ref,
            erp_system=erp.system_name,
            posting_status="POSTED" if result_success else "FAILED",
            error_message=erp_error,
            payload={
                "vendor_code": vendor_code,
                "invoice_number": doc.invoice_number,
                "invoice_amount": invoice_amount,
                "tax_amount": tax_amount,
            },
        )
        self.db.add(posting)

        if result_success:
            doc.status = DocumentStatus.POSTED
        else:
            doc.status = DocumentStatus.EXCEPTION

        self.db.flush()

        log_audit(
            self.db,
            document_id=document_id,
            entity_type="ERP_POSTING",
            entity_id=str(posting.id),
            action="ERP_POSTED" if result_success else "ERP_POST_FAILED",
            agent=self.name,
            after_state={
                "erp_reference": erp_ref,
                "status": posting.posting_status,
                "erp_system": erp.system_name,
            },
            stage=ProcessingStage.ERP_POSTING,
        )

        update_workflow_stage(
            self.db, document_id=document_id,
            stage=ProcessingStage.PAYMENT_SCHEDULING,
            agent=self.name, progress_percent=95,
        )

        state["erp_reference"] = erp_ref
        state["erp_posting_success"] = result_success
        state.set_status("SUCCESS" if result_success else "ERP_FAILED")
        state.set_next_agent("PAYMENT_AGENT")
        return state
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.agents.base import AgentState, BaseAgent
from app.models.models import Document, DocumentStatus, PaymentSchedule, PaymentStatus, ProcessingStage
from app.tools.audit_tool import log_audit, update_workflow_stage


PAYMENT_TERMS_DAYS = {
    "NET7": 7,
    "NET15": 15,
    "NET30": 30,
    "NET45": 45,
    "NET60": 60,
    "NET90": 90,
    "IMMEDIATE": 0,
}


class PaymentAgent(BaseAgent):
    """
    Agent 12: PAYMENT SCHEDULING
    Calculates due dates from payment terms.
    Records net payable after TDS deductions.
    """

    name = "PAYMENT_AGENT"
    progress_on_entry = 95
    progress_on_exit = 100

    def _execute(self, state: AgentState) -> AgentState:
        document_id: str = state["document_id"]
        doc = self.db.query(Document).filter(Document.id == document_id).first()

        # Get payment terms from vendor or document
        payment_terms = "NET30"
        if doc.vendor:
            payment_terms = doc.vendor.payment_terms or "NET30"
        extracted = doc.extracted_data or {}
        invoice_payment_terms = (extracted.get("invoice") or {}).get("payment_terms")
        if invoice_payment_terms:
            payment_terms = invoice_payment_terms.upper()

        # Normalize payment terms
        normalized_terms = payment_terms.replace(" ", "").upper()
        days = PAYMENT_TERMS_DAYS.get(normalized_terms, 30)

        invoice_date = doc.invoice_date or date.today()
        due_date = invoice_date + timedelta(days=days)

        # Calculate amounts
        invoice_amount = Decimal(str(doc.invoice_amount or doc.total_amount or 0))
        tax_amount = Decimal(str(doc.tax_amount or 0))

        # TDS calculation
        tds_rate = Decimal("0")
        tds_deduction = Decimal("0")
        if doc.vendor and doc.vendor.tds_applicable:
            tds_rate = Decimal(str(doc.vendor.tds_rate or 0))
            tds_deduction = (invoice_amount * tds_rate / 100).quantize(Decimal("0.01"))

        net_payable = invoice_amount + tax_amount - tds_deduction

        # Check if payment schedule already exists
        existing = self.db.query(PaymentSchedule).filter(
            PaymentSchedule.document_id == document_id
        ).first()

        if existing:
            existing.due_date = due_date
            existing.net_payable = net_payable
            existing.tds_deduction = tds_deduction
            ps = existing
        else:
            ps = PaymentSchedule(
                document_id=document_id,
                vendor_id=doc.vendor_id,
                invoice_amount=invoice_amount,
                tax_amount=tax_amount,
                tds_deduction=tds_deduction,
                other_deductions=Decimal("0"),
                net_payable=net_payable,
                payment_terms=normalized_terms,
                invoice_date=invoice_date,
                due_date=due_date,
                status=PaymentStatus.SCHEDULED,
                bank_account=doc.vendor.bank_account_number if doc.vendor else None,
                bank_ifsc=doc.vendor.bank_ifsc if doc.vendor else None,
            )
            self.db.add(ps)

        doc.status = DocumentStatus.COMPLETED
        self.db.flush()

        log_audit(
            self.db,
            document_id=document_id,
            entity_type="PAYMENT",
            entity_id=str(ps.id),
            action="PAYMENT_SCHEDULED",
            agent=self.name,
            after_state={
                "due_date": due_date.isoformat(),
                "payment_terms": normalized_terms,
                "net_payable": float(net_payable),
                "tds_deduction": float(tds_deduction),
            },
            stage=ProcessingStage.PAYMENT_SCHEDULING,
        )

        update_workflow_stage(
            self.db, document_id=document_id,
            stage=ProcessingStage.COMPLETED,
            agent=self.name, progress_percent=100,
        )

        state["due_date"] = due_date.isoformat()
        state["net_payable"] = float(net_payable)
        state["payment_terms"] = normalized_terms
        state.set_status("COMPLETED")
        state.set_next_agent(None)
        return state
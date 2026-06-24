"""PostingTool — post a validated invoice to the ERP system via the ERPProviderInterface."""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from typing import ClassVar, Dict, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class ERPPostingInput(ToolInput):
    document_id: str
    vendor_code: str
    invoice_number: str
    invoice_amount: float
    tax_amount: float
    currency: str = "INR"
    journal_entries: List[Dict]
    cost_center: Optional[str] = None
    gl_code: Optional[str] = None
    purchase_order: Optional[str] = None
    payment_terms: Optional[str] = None
    posting_date: Optional[str] = None
    tenant_id: str = "default"


class ERPPostingOutput(ToolOutput):
    erp_reference: Optional[str] = None
    posting_status: str = "FAILED"
    erp_message: Optional[str] = None
    raw_response: Optional[Dict] = None
    error_code: Optional[str] = None


class PostingTool(BaseTool[ERPPostingInput, ERPPostingOutput]):
    name: ClassVar[str] = "erp_posting"
    description: ClassVar[str] = "Post a validated invoice to the ERP system"
    input_model: ClassVar = ERPPostingInput
    output_model: ClassVar = ERPPostingOutput

    def __init__(self, erp_provider=None, **kwargs):
        super().__init__(**kwargs)
        self._erp = erp_provider

    def _get_erp(self):
        if self._erp is None:
            from core.container import get_container
            self._erp = get_container().erp_provider
        return self._erp

    def _execute(self, input_data: ERPPostingInput) -> ERPPostingOutput:
        try:
            from core.providers.erp_provider import ERPInvoicePayload
            erp = self._get_erp()
            payload = ERPInvoicePayload(
                document_id=input_data.document_id,
                posting_date=input_data.posting_date or date.today().isoformat(),
                vendor_code=input_data.vendor_code,
                invoice_number=input_data.invoice_number,
                invoice_amount=Decimal(str(input_data.invoice_amount)),
                tax_amount=Decimal(str(input_data.tax_amount)),
                net_payable=Decimal(str(input_data.invoice_amount + input_data.tax_amount)),
                currency=input_data.currency,
                journal_entries=input_data.journal_entries,
                cost_center=input_data.cost_center,
                gl_code=input_data.gl_code,
                purchase_order=input_data.purchase_order,
                payment_terms=input_data.payment_terms,
            )
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(erp.post_invoice(payload))

            return ERPPostingOutput(
                success=result.success,
                erp_reference=result.erp_reference if result.success else None,
                posting_status="POSTED" if result.success else "FAILED",
                erp_message=result.message,
                raw_response=result.raw_response,
                error_code=None if result.success else "ERP_POSTING_FAILED",
            )
        except Exception as exc:
            return ERPPostingOutput(
                success=False,
                posting_status="FAILED",
                error_code="ERP_POSTING_EXCEPTION",
                error_message=str(exc),
            )


class PaymentScheduleInput(ToolInput):
    document_id: str
    invoice_total: float
    payment_terms: Optional[str] = "NET30"
    invoice_date: Optional[str] = None
    currency: str = "INR"


class PaymentScheduleOutput(ToolOutput):
    scheduled_date: Optional[str] = None
    payment_amount: float = 0.0
    discount_if_early: float = 0.0
    payment_reference: Optional[str] = None


class PaymentScheduleTool(BaseTool[PaymentScheduleInput, PaymentScheduleOutput]):
    name: ClassVar[str] = "payment_schedule"
    description: ClassVar[str] = "Compute payment due date and schedule from payment terms"
    input_model: ClassVar = PaymentScheduleInput
    output_model: ClassVar = PaymentScheduleOutput

    def _execute(self, input_data: PaymentScheduleInput) -> PaymentScheduleOutput:
        import re
        from datetime import date, timedelta

        terms = input_data.payment_terms or "NET30"
        match = re.search(r"\d+", terms)
        days = int(match.group()) if match else 30

        if input_data.invoice_date:
            try:
                from datetime import datetime
                base = datetime.strptime(input_data.invoice_date, "%Y-%m-%d").date()
            except Exception:
                base = date.today()
        else:
            base = date.today()

        due_date = base + timedelta(days=days)

        return PaymentScheduleOutput(
            success=True,
            scheduled_date=due_date.isoformat(),
            payment_amount=input_data.invoice_total,
        )

"""JournalEntryTool — build double-entry journal entries for ERP posting."""
from __future__ import annotations

from typing import ClassVar, Dict, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class JournalEntryInput(ToolInput):
    vendor_code: str
    invoice_amount: float
    tax_amount: float
    gl_code: str = "5001"
    tax_gl_code: str = "1401"
    ap_gl_code: str = "2001"
    cost_center: str = ""
    currency: str = "INR"
    document_id: Optional[str] = None


class JournalEntry(ToolInput):
    account: str
    description: str
    debit: float
    credit: float
    cost_center: str = ""
    currency: str = "INR"


class JournalEntryOutput(ToolOutput):
    entries: List[JournalEntry] = []
    total_debits: float = 0.0
    total_credits: float = 0.0
    is_balanced: bool = False
    error_code: Optional[str] = None


class JournalEntryTool(BaseTool[JournalEntryInput, JournalEntryOutput]):
    name: ClassVar[str] = "journal_entry"
    description: ClassVar[str] = "Build balanced double-entry journal entries for an invoice"
    input_model: ClassVar = JournalEntryInput
    output_model: ClassVar = JournalEntryOutput

    def _execute(self, input_data: JournalEntryInput) -> JournalEntryOutput:
        entries = [
            JournalEntry(
                account=input_data.gl_code,
                description="Expense / Asset",
                debit=round(input_data.invoice_amount, 2),
                credit=0.0,
                cost_center=input_data.cost_center,
                currency=input_data.currency,
            ),
            JournalEntry(
                account=input_data.tax_gl_code,
                description="Input Tax Credit (GST)",
                debit=round(input_data.tax_amount, 2),
                credit=0.0,
                cost_center=input_data.cost_center,
                currency=input_data.currency,
            ),
            JournalEntry(
                account=input_data.ap_gl_code,
                description=f"Accounts Payable - {input_data.vendor_code}",
                debit=0.0,
                credit=round(input_data.invoice_amount + input_data.tax_amount, 2),
                cost_center=input_data.cost_center,
                currency=input_data.currency,
            ),
        ]

        total_debits = sum(e.debit for e in entries)
        total_credits = sum(e.credit for e in entries)
        is_balanced = abs(total_debits - total_credits) < 0.01

        return JournalEntryOutput(
            success=True,
            entries=entries,
            total_debits=round(total_debits, 2),
            total_credits=round(total_credits, 2),
            is_balanced=is_balanced,
        )

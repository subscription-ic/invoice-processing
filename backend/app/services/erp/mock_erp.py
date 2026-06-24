from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.services.erp.base import ERPPostingPayload, ERPPostingResult, ERPProvider


class MockERPProvider(ERPProvider):
    """
    Mock ERP that uses PostgreSQL as the source of truth.
    All validations and matching use data from the DB tables (vendors, POs, GRNs, etc.)
    Final postings write ERP journal entries into erp_postings table.
    """

    @property
    def system_name(self) -> str:
        return "MOCK"

    async def post_invoice(self, payload: ERPPostingPayload) -> ERPPostingResult:
        erp_ref = f"MOCK-{date.today().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
        return ERPPostingResult(
            success=True,
            erp_reference=erp_ref,
            message="Successfully posted to Mock ERP",
            raw_response={
                "erp_system": "MOCK",
                "reference": erp_ref,
                "status": "POSTED",
                "journal_entries": payload.journal_entries,
                "timestamp": date.today().isoformat(),
            },
        )

    async def get_purchase_order(self, po_number: str) -> Optional[Dict[str, Any]]:
        # In mock mode, data is fetched directly from PostgreSQL in the agents.
        return None

    async def get_vendor(self, vendor_code: str) -> Optional[Dict[str, Any]]:
        return None

    async def health_check(self) -> bool:
        return True

    @staticmethod
    def build_journal_entries(
        vendor_code: str,
        invoice_amount: float,
        tax_amount: float,
        gl_code: str = "5001",
        tax_gl_code: str = "1401",
        ap_gl_code: str = "2001",
        cost_center: str = "",
    ) -> list:
        """Build double-entry journal for invoice posting."""
        entries = [
            {
                "account": gl_code,
                "description": "Expense / Asset",
                "debit": invoice_amount,
                "credit": 0,
                "cost_center": cost_center,
            },
            {
                "account": tax_gl_code,
                "description": "Input Tax Credit (GST)",
                "debit": tax_amount,
                "credit": 0,
                "cost_center": cost_center,
            },
            {
                "account": ap_gl_code,
                "description": f"Accounts Payable - {vendor_code}",
                "debit": 0,
                "credit": invoice_amount + tax_amount,
                "cost_center": cost_center,
            },
        ]
        return entries


_erp_provider: MockERPProvider | None = None


def get_erp_provider() -> MockERPProvider:
    global _erp_provider
    if _erp_provider is None:
        _erp_provider = MockERPProvider()
    return _erp_provider
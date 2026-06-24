"""NormalizationTool — normalise extracted field values to standard formats."""
from __future__ import annotations

import re
from datetime import datetime
from typing import ClassVar, Dict, List, Optional, Tuple

from core.base.tool import BaseTool, ToolInput, ToolOutput


class NormalizationInput(ToolInput):
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    total_amount: Optional[str] = None
    tax_amount: Optional[str] = None
    vendor_gstin: Optional[str] = None
    currency: Optional[str] = None
    payment_terms: Optional[str] = None


class NormalizationOutput(ToolOutput):
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    total_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    vendor_gstin: Optional[str] = None
    currency: str = "INR"
    payment_terms: Optional[str] = None
    normalization_notes: List[str] = []


_DATE_FORMATS = [
    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y",
    "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
    "%d/%m/%y", "%d-%m-%y",
]


class NormalizationTool(BaseTool[NormalizationInput, NormalizationOutput]):
    name: ClassVar[str] = "normalization"
    description: ClassVar[str] = "Normalise extracted invoice fields to canonical formats"
    input_model: ClassVar = NormalizationInput
    output_model: ClassVar = NormalizationOutput

    def _execute(self, input_data: NormalizationInput) -> NormalizationOutput:
        notes = []

        invoice_number = self._normalize_invoice_number(input_data.invoice_number)
        invoice_date = self._parse_date(input_data.invoice_date, "invoice_date", notes)
        due_date = self._parse_date(input_data.due_date, "due_date", notes)
        total_amount = self._parse_amount(input_data.total_amount, "total_amount", notes)
        tax_amount = self._parse_amount(input_data.tax_amount, "tax_amount", notes)
        gstin = self._normalize_gstin(input_data.vendor_gstin)
        currency = self._normalize_currency(input_data.currency)
        payment_terms = self._normalize_payment_terms(input_data.payment_terms)

        return NormalizationOutput(
            success=True,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            due_date=due_date,
            total_amount=total_amount,
            tax_amount=tax_amount,
            vendor_gstin=gstin,
            currency=currency,
            payment_terms=payment_terms,
            normalization_notes=notes,
        )

    def _normalize_invoice_number(self, val: Optional[str]) -> Optional[str]:
        if not val:
            return None
        return re.sub(r"\s+", "", val.strip().upper())

    def _parse_date(self, val: Optional[str], field: str, notes: List[str]) -> Optional[str]:
        if not val:
            return None
        val = val.strip()
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
        notes.append(f"{field}: could not parse date '{val}'")
        return val

    def _parse_amount(self, val: Optional[str], field: str, notes: List[str]) -> Optional[float]:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        cleaned = re.sub(r"[^\d.]", "", str(val))
        try:
            return float(cleaned)
        except ValueError:
            notes.append(f"{field}: could not parse amount '{val}'")
            return None

    def _normalize_gstin(self, val: Optional[str]) -> Optional[str]:
        if not val:
            return None
        return re.sub(r"\s+", "", val.strip().upper())

    def _normalize_currency(self, val: Optional[str]) -> str:
        if not val:
            return "INR"
        mapping = {
            "rs": "INR", "inr": "INR", "₹": "INR",
            "usd": "USD", "$": "USD",
            "eur": "EUR", "€": "EUR",
        }
        return mapping.get(val.lower().strip(), val.upper())

    def _normalize_payment_terms(self, val: Optional[str]) -> Optional[str]:
        if not val:
            return None
        val = val.strip()
        # Normalise "Net 30", "Net30", "30 days", etc. → "NET30"
        m = re.search(r"\d+", val)
        if m:
            days = int(m.group())
            if "advance" in val.lower():
                return f"ADVANCE{days}"
            return f"NET{days}"
        if "immediate" in val.lower() or "due on receipt" in val.lower():
            return "NET0"
        return val.upper()

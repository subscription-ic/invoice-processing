from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class ERPPostingPayload:
    document_id: str
    posting_date: str
    vendor_code: str
    invoice_number: str
    invoice_amount: Decimal
    tax_amount: Decimal
    net_payable: Decimal
    currency: str
    journal_entries: List[Dict[str, Any]]
    cost_center: Optional[str] = None
    gl_code: Optional[str] = None
    purchase_order: Optional[str] = None
    payment_terms: Optional[str] = None
    metadata: Dict[str, Any] = None


@dataclass
class ERPPostingResult:
    success: bool
    erp_reference: str
    message: str
    raw_response: Dict[str, Any] = None


class ERPProvider(ABC):
    """Abstract ERP posting provider. Implementations: MockERP, SAPProvider, OracleProvider."""

    @abstractmethod
    async def post_invoice(self, payload: ERPPostingPayload) -> ERPPostingResult:
        """Post an invoice to the ERP system."""

    @abstractmethod
    async def get_purchase_order(self, po_number: str) -> Optional[Dict[str, Any]]:
        """Fetch PO details from ERP."""

    @abstractmethod
    async def get_vendor(self, vendor_code: str) -> Optional[Dict[str, Any]]:
        """Fetch vendor master from ERP."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if ERP is reachable."""

    @property
    @abstractmethod
    def system_name(self) -> str:
        """ERP system identifier."""
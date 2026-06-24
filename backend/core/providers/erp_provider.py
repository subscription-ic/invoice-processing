"""
ERPProvider — platform-level interface wrapping the existing app/services/erp layer.

The platform core interacts with this interface only.
The underlying implementation is resolved by the DI container at startup.

Production guard: if allow_mock_in_production is False and the environment is
production, MockERPProvider will raise MockInProductionException.
"""

from __future__ import annotations

from abc import abstractmethod
from decimal import Decimal
from typing import Any, ClassVar, Dict, List, Optional

from core.base.provider import BaseProvider


class ERPInvoicePayload:
    """Platform-level invoice posting payload (mirrors ERPPostingPayload)."""

    __slots__ = (
        "document_id",
        "posting_date",
        "vendor_code",
        "invoice_number",
        "invoice_amount",
        "tax_amount",
        "net_payable",
        "currency",
        "journal_entries",
        "cost_center",
        "gl_code",
        "purchase_order",
        "payment_terms",
        "metadata",
    )

    def __init__(
        self,
        document_id: str,
        posting_date: str,
        vendor_code: str,
        invoice_number: str,
        invoice_amount: Decimal,
        tax_amount: Decimal,
        net_payable: Decimal,
        currency: str,
        journal_entries: List[Dict[str, Any]],
        cost_center: Optional[str] = None,
        gl_code: Optional[str] = None,
        purchase_order: Optional[str] = None,
        payment_terms: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.document_id = document_id
        self.posting_date = posting_date
        self.vendor_code = vendor_code
        self.invoice_number = invoice_number
        self.invoice_amount = invoice_amount
        self.tax_amount = tax_amount
        self.net_payable = net_payable
        self.currency = currency
        self.journal_entries = journal_entries
        self.cost_center = cost_center
        self.gl_code = gl_code
        self.purchase_order = purchase_order
        self.payment_terms = payment_terms
        self.metadata = metadata or {}


class ERPPostingResult:
    """Result of an ERP posting operation."""

    __slots__ = ("success", "erp_reference", "message", "raw_response")

    def __init__(
        self,
        success: bool,
        erp_reference: str,
        message: str,
        raw_response: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.success = success
        self.erp_reference = erp_reference
        self.message = message
        self.raw_response = raw_response or {}


class ERPProviderInterface(BaseProvider):
    """
    Abstract ERP provider interface.

    Implementations: MockERPAdapter (active), SAPERPAdapter, OracleERPAdapter (stubs).
    """

    provider_type: ClassVar[str] = "erp"

    @abstractmethod
    async def post_invoice(self, payload: ERPInvoicePayload) -> ERPPostingResult:
        """Post a validated invoice to the ERP system."""

    @abstractmethod
    async def get_purchase_order(self, po_number: str) -> Optional[Dict[str, Any]]:
        """Fetch PO master data from ERP."""

    @abstractmethod
    async def get_vendor(self, vendor_code: str) -> Optional[Dict[str, Any]]:
        """Fetch vendor master data from ERP."""


class MockERPAdapter(ERPProviderInterface):
    """
    Thin adapter over the existing MockERPProvider.

    Delegates all work to the legacy implementation so that existing agent
    behaviour is preserved during the migration.
    """

    provider_name: ClassVar[str] = "mock_erp"

    def __init__(self, allow_mock_in_production: bool = False) -> None:
        self._allow_mock_in_production = allow_mock_in_production

    def _guard_production(self) -> None:
        from app.core.config import settings

        env = getattr(settings, "ENVIRONMENT", "development").lower()
        if env == "production" and not self._allow_mock_in_production:
            from core.base.exceptions import MockInProductionException
            raise MockInProductionException("MockERPProvider")

    async def health_check(self) -> bool:
        return True

    async def post_invoice(self, payload: ERPInvoicePayload) -> ERPPostingResult:
        self._guard_production()
        from app.services.erp.mock_erp import get_erp_provider
        from app.services.erp.base import ERPPostingPayload

        legacy = get_erp_provider()
        legacy_payload = ERPPostingPayload(
            document_id=payload.document_id,
            posting_date=payload.posting_date,
            vendor_code=payload.vendor_code,
            invoice_number=payload.invoice_number,
            invoice_amount=payload.invoice_amount,
            tax_amount=payload.tax_amount,
            net_payable=payload.net_payable,
            currency=payload.currency,
            journal_entries=payload.journal_entries,
            cost_center=payload.cost_center,
            gl_code=payload.gl_code,
            purchase_order=payload.purchase_order,
            payment_terms=payload.payment_terms,
            metadata=payload.metadata,
        )
        result = await legacy.post_invoice(legacy_payload)
        return ERPPostingResult(
            success=result.success,
            erp_reference=result.erp_reference,
            message=result.message,
            raw_response=result.raw_response or {},
        )

    async def get_purchase_order(self, po_number: str) -> Optional[Dict[str, Any]]:
        self._guard_production()
        from app.services.erp.mock_erp import get_erp_provider

        return await get_erp_provider().get_purchase_order(po_number)

    async def get_vendor(self, vendor_code: str) -> Optional[Dict[str, Any]]:
        self._guard_production()
        from app.services.erp.mock_erp import get_erp_provider

        return await get_erp_provider().get_vendor(vendor_code)

    @staticmethod
    def build_journal_entries(
        vendor_code: str,
        invoice_amount: float,
        tax_amount: float,
        gl_code: str = "5001",
        tax_gl_code: str = "1401",
        ap_gl_code: str = "2001",
        cost_center: str = "",
    ) -> List[Dict[str, Any]]:
        from app.services.erp.mock_erp import MockERPProvider

        return MockERPProvider.build_journal_entries(
            vendor_code=vendor_code,
            invoice_amount=invoice_amount,
            tax_amount=tax_amount,
            gl_code=gl_code,
            tax_gl_code=tax_gl_code,
            ap_gl_code=ap_gl_code,
            cost_center=cost_center,
        )

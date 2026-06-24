from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.erp.base import ERPPostingPayload, ERPPostingResult, ERPProvider


class SAPProvider(ERPProvider):
    """
    Future: SAP S/4HANA integration via REST/BAPI/RFC.
    Requires: SAP host, client, username, password or OAuth2 client credentials.
    """

    @property
    def system_name(self) -> str:
        return "SAP"

    async def post_invoice(self, payload: ERPPostingPayload) -> ERPPostingResult:
        raise NotImplementedError("SAP integration not yet implemented.")

    async def get_purchase_order(self, po_number: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def get_vendor(self, vendor_code: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def health_check(self) -> bool:
        return False


class OracleProvider(ERPProvider):
    """Future: Oracle Fusion Cloud integration via REST APIs."""

    @property
    def system_name(self) -> str:
        return "ORACLE"

    async def post_invoice(self, payload: ERPPostingPayload) -> ERPPostingResult:
        raise NotImplementedError("Oracle integration not yet implemented.")

    async def get_purchase_order(self, po_number: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def get_vendor(self, vendor_code: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def health_check(self) -> bool:
        return False
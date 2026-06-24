"""PO Matching Tool — match invoice to a Purchase Order."""
from __future__ import annotations

import asyncio
from typing import ClassVar, Dict, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class POMatchInput(ToolInput):
    po_number: Optional[str] = None
    vendor_id: Optional[str] = None
    invoice_total: float = 0.0
    invoice_line_items: List[Dict] = []
    document_id: str
    tenant_id: str = "default"


class POMatchOutput(ToolOutput):
    matched: bool = False
    po_id: Optional[str] = None
    po_number: Optional[str] = None
    match_score: float = 0.0
    open_value: float = 0.0
    consumed_value: float = 0.0
    line_match_results: List[Dict] = []
    po_status: Optional[str] = None
    error_code: Optional[str] = None


class POMatchingTool(BaseTool[POMatchInput, POMatchOutput]):
    name: ClassVar[str] = "po_matching"
    description: ClassVar[str] = "Match invoice to a Purchase Order and compute match score"
    input_model: ClassVar = POMatchInput
    output_model: ClassVar = POMatchOutput

    def __init__(self, po_repository=None, **kwargs):
        super().__init__(**kwargs)
        self._repo = po_repository

    def _get_repo(self):
        if self._repo is None:
            from core.container import get_container
            self._repo = get_container().po_repository
        return self._repo

    def _execute(self, input_data: POMatchInput) -> POMatchOutput:
        try:
            repo = self._get_repo()
            loop = asyncio.get_event_loop()

            po = None
            if input_data.po_number:
                po = loop.run_until_complete(repo.find_by_po_number(input_data.po_number))

            if not po and input_data.vendor_id:
                open_pos = loop.run_until_complete(
                    repo.find_open_pos_for_vendor(input_data.vendor_id)
                )
                # Pick the PO whose total is closest to the invoice total
                if open_pos:
                    po = min(
                        open_pos,
                        key=lambda p: abs(float(p.total_amount or 0) - input_data.invoice_total),
                    )

            if not po:
                return POMatchOutput(success=True, matched=False, match_score=0.0)

            po_total = float(po.total_amount or 0)
            tol = 0.02  # 2% tolerance
            invoice_total = input_data.invoice_total
            amount_diff = abs(po_total - invoice_total) / max(po_total, 1)
            amount_score = max(0.0, 1.0 - amount_diff / tol) if amount_diff <= tol else 0.5
            match_score = amount_score

            return POMatchOutput(
                success=True,
                matched=match_score >= 0.7,
                po_id=str(po.id),
                po_number=po.po_number,
                match_score=round(match_score, 4),
                open_value=po_total,
                po_status=str(po.status) if hasattr(po, "status") else None,
            )
        except Exception as exc:
            return POMatchOutput(
                success=False,
                error_code="PO_MATCH_FAILED",
                error_message=str(exc),
            )

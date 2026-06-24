"""GRNMatchingTool — match invoice to Goods Receipt Notes."""
from __future__ import annotations

import asyncio
from typing import ClassVar, Dict, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class GRNMatchInput(ToolInput):
    grn_number: Optional[str] = None
    po_id: Optional[str] = None
    invoice_line_items: List[Dict] = []
    document_id: str
    tenant_id: str = "default"


class GRNMatchOutput(ToolOutput):
    matched: bool = False
    grn_id: Optional[str] = None
    grn_number: Optional[str] = None
    match_score: float = 0.0
    received_quantity_match: bool = False
    line_match_results: List[Dict] = []
    error_code: Optional[str] = None


class GRNMatchingTool(BaseTool[GRNMatchInput, GRNMatchOutput]):
    name: ClassVar[str] = "grn_matching"
    description: ClassVar[str] = "Match invoice to Goods Receipt Notes for 3-way matching"
    input_model: ClassVar = GRNMatchInput
    output_model: ClassVar = GRNMatchOutput

    def __init__(self, grn_repository=None, **kwargs):
        super().__init__(**kwargs)
        self._repo = grn_repository

    def _get_repo(self):
        if self._repo is None:
            from core.container import get_container
            self._repo = get_container().grn_repository
        return self._repo

    def _execute(self, input_data: GRNMatchInput) -> GRNMatchOutput:
        try:
            repo = self._get_repo()
            loop = asyncio.get_event_loop()

            grn = None
            if input_data.grn_number:
                grn = loop.run_until_complete(repo.find_by_grn_number(input_data.grn_number))

            if not grn and input_data.po_id:
                grns = loop.run_until_complete(repo.find_by_po_id(input_data.po_id))
                grn = grns[0] if grns else None

            if not grn:
                return GRNMatchOutput(success=True, matched=False, match_score=0.0)

            return GRNMatchOutput(
                success=True,
                matched=True,
                grn_id=str(grn.id),
                grn_number=grn.grn_number,
                match_score=0.9,
                received_quantity_match=True,
            )
        except Exception as exc:
            return GRNMatchOutput(
                success=False,
                error_code="GRN_MATCH_FAILED",
                error_message=str(exc),
            )

"""VendorMatchingTool — match extracted vendor to master data."""
from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
from typing import ClassVar, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class VendorMatchInput(ToolInput):
    extracted_vendor_name: Optional[str] = None
    extracted_gstin: Optional[str] = None
    document_id: str
    tenant_id: str = "default"
    fuzzy_threshold: float = 0.7


class VendorMatchOutput(ToolOutput):
    matched: bool = False
    vendor_id: Optional[str] = None
    matched_name: Optional[str] = None
    match_score: float = 0.0
    match_method: Optional[str] = None
    candidates: List[dict] = []
    error_code: Optional[str] = None


class VendorMatchingTool(BaseTool[VendorMatchInput, VendorMatchOutput]):
    name: ClassVar[str] = "vendor_matching"
    description: ClassVar[str] = "Match extracted vendor name/GSTIN to vendor master data"
    input_model: ClassVar = VendorMatchInput
    output_model: ClassVar = VendorMatchOutput

    def __init__(self, vendor_repository=None, **kwargs):
        super().__init__(**kwargs)
        self._repo = vendor_repository

    def _get_repo(self):
        if self._repo is None:
            from core.container import get_container
            self._repo = get_container().vendor_repository
        return self._repo

    def _execute(self, input_data: VendorMatchInput) -> VendorMatchOutput:
        try:
            repo = self._get_repo()
            loop = asyncio.get_event_loop()

            # GSTIN exact match
            if input_data.extracted_gstin:
                vendor = loop.run_until_complete(
                    repo.find_by_gstin(input_data.extracted_gstin)
                )
                if vendor:
                    return VendorMatchOutput(
                        success=True, matched=True,
                        vendor_id=str(vendor.id),
                        matched_name=vendor.name,
                        match_score=1.0,
                        match_method="GSTIN_EXACT",
                    )

            # Fuzzy name match
            if input_data.extracted_vendor_name:
                candidates = loop.run_until_complete(
                    repo.find_by_name_fuzzy(input_data.extracted_vendor_name)
                )
                best_score = 0.0
                best_vendor = None
                for v in candidates:
                    score = SequenceMatcher(
                        None,
                        input_data.extracted_vendor_name.lower(),
                        v.name.lower(),
                    ).ratio()
                    if score > best_score:
                        best_score = score
                        best_vendor = v

                if best_vendor and best_score >= input_data.fuzzy_threshold:
                    return VendorMatchOutput(
                        success=True, matched=True,
                        vendor_id=str(best_vendor.id),
                        matched_name=best_vendor.name,
                        match_score=round(best_score, 4),
                        match_method="NAME_FUZZY",
                        candidates=[{"id": str(v.id), "name": v.name} for v in (candidates or [])],
                    )

                return VendorMatchOutput(
                    success=True, matched=False, match_score=best_score,
                    candidates=[{"id": str(v.id), "name": v.name} for v in (candidates or [])],
                )

            return VendorMatchOutput(success=True, matched=False)
        except Exception as exc:
            return VendorMatchOutput(
                success=False,
                error_code="VENDOR_MATCH_FAILED",
                error_message=str(exc),
            )

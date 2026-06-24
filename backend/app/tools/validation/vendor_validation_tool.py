"""VendorValidationTool — validate vendor existence and status in master data."""
from __future__ import annotations

import asyncio
from typing import ClassVar, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class VendorValidationInput(ToolInput):
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    document_id: Optional[str] = None
    tenant_id: str = "default"


class VendorValidationOutput(ToolOutput):
    vendor_found: bool = False
    vendor_id: Optional[str] = None
    vendor_active: bool = False
    name_match_score: float = 0.0
    gstin_match: bool = False
    is_blacklisted: bool = False
    matched_vendor_name: Optional[str] = None
    error_code: Optional[str] = None


class VendorValidationTool(BaseTool[VendorValidationInput, VendorValidationOutput]):
    name: ClassVar[str] = "vendor_validation"
    description: ClassVar[str] = "Validate vendor against master data — check existence, status, GSTIN"
    input_model: ClassVar = VendorValidationInput
    output_model: ClassVar = VendorValidationOutput

    def __init__(self, vendor_repository=None, **kwargs):
        super().__init__(**kwargs)
        self._vendor_repo = vendor_repository

    def _get_repo(self):
        if self._vendor_repo is None:
            from core.container import get_container
            self._vendor_repo = get_container().vendor_repository
        return self._vendor_repo

    def _execute(self, input_data: VendorValidationInput) -> VendorValidationOutput:
        try:
            repo = self._get_repo()
            loop = asyncio.get_event_loop()

            # Try GSTIN match first (most reliable)
            if input_data.vendor_gstin:
                vendor = loop.run_until_complete(
                    repo.find_by_gstin(input_data.vendor_gstin)
                )
                if vendor:
                    return VendorValidationOutput(
                        success=True,
                        vendor_found=True,
                        vendor_id=str(vendor.id),
                        vendor_active=vendor.is_active,
                        gstin_match=True,
                        name_match_score=1.0 if input_data.vendor_name and vendor.name.lower() == input_data.vendor_name.lower() else 0.7,
                        matched_vendor_name=vendor.name,
                    )

            # Fuzzy name match
            if input_data.vendor_name:
                vendors = loop.run_until_complete(
                    repo.find_by_name_fuzzy(input_data.vendor_name)
                )
                if vendors:
                    best = vendors[0]
                    return VendorValidationOutput(
                        success=True,
                        vendor_found=True,
                        vendor_id=str(best.id),
                        vendor_active=best.is_active,
                        gstin_match=False,
                        name_match_score=0.7,
                        matched_vendor_name=best.name,
                    )

            return VendorValidationOutput(success=True, vendor_found=False, vendor_active=False)
        except Exception as exc:
            return VendorValidationOutput(
                success=False,
                error_code="VENDOR_LOOKUP_FAILED",
                error_message=str(exc),
            )

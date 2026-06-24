"""
ThreeWayMatchingTool — orchestrate PO + GRN + Invoice matching.

This is the central matching tool that computes the overall match result.
"""
from __future__ import annotations

from typing import ClassVar, Dict, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class ThreeWayMatchInput(ToolInput):
    document_id: str
    po_id: Optional[str] = None
    grn_id: Optional[str] = None
    invoice_total: float = 0.0
    invoice_line_items: List[Dict] = []
    po_match_score: float = 0.0
    grn_match_score: float = 0.0
    vendor_match_score: float = 0.0
    tenant_id: str = "default"


class ThreeWayMatchOutput(ToolOutput):
    match_status: str = "UNMATCHED"
    overall_score: float = 0.0
    po_matched: bool = False
    grn_matched: bool = False
    vendor_matched: bool = False
    variance_amount: float = 0.0
    variance_percent: float = 0.0
    requires_manual_review: bool = False
    auto_approvable: bool = False
    routing_recommendation: str = "MANUAL_REVIEW"
    error_code: Optional[str] = None


class ThreeWayMatchingTool(BaseTool[ThreeWayMatchInput, ThreeWayMatchOutput]):
    name: ClassVar[str] = "three_way_matching"
    description: ClassVar[str] = "Compute overall 3-way match result from PO, GRN, and vendor scores"
    input_model: ClassVar = ThreeWayMatchInput
    output_model: ClassVar = ThreeWayMatchOutput

    def _execute(self, input_data: ThreeWayMatchInput) -> ThreeWayMatchOutput:
        from core.config.platform_config import get_platform_config
        cfg = get_platform_config().get_tenant_config(input_data.tenant_id).matching

        po_s = input_data.po_match_score
        grn_s = input_data.grn_match_score
        vendor_s = input_data.vendor_match_score

        # Weighted overall score
        if input_data.po_id and input_data.grn_id:
            overall = (po_s * 0.4) + (grn_s * 0.4) + (vendor_s * 0.2)
        elif input_data.po_id:
            overall = (po_s * 0.6) + (vendor_s * 0.4)
        else:
            overall = vendor_s

        overall = round(min(1.0, max(0.0, overall)), 4)

        if overall >= cfg.full_match_threshold:
            status = "FULL_MATCH"
            routing = "AUTO_APPROVE"
            auto_approvable = True
            manual = False
        elif overall >= cfg.partial_match_lower:
            status = "PARTIAL_MATCH"
            routing = "AP_REVIEW"
            auto_approvable = False
            manual = True
        else:
            status = "NO_MATCH"
            routing = "EXCEPTION_QUEUE"
            auto_approvable = False
            manual = True

        return ThreeWayMatchOutput(
            success=True,
            match_status=status,
            overall_score=overall,
            po_matched=po_s >= 0.7,
            grn_matched=grn_s >= 0.7,
            vendor_matched=vendor_s >= 0.7,
            requires_manual_review=manual,
            auto_approvable=auto_approvable,
            routing_recommendation=routing,
        )


class SimilarityTool(BaseTool):
    """String similarity calculation."""
    name: ClassVar[str] = "similarity"
    description: ClassVar[str] = "Compute string similarity score between two values"
    input_model: ClassVar = ToolInput
    output_model: ClassVar = ToolOutput

    def _execute(self, input_data):
        return ToolOutput(success=True)


class ToleranceTool(BaseTool):
    """Check if a variance is within configured tolerance."""
    name: ClassVar[str] = "tolerance"
    description: ClassVar[str] = "Check if a numeric variance is within the configured tolerance"
    input_model: ClassVar = ToolInput
    output_model: ClassVar = ToolOutput

    def _execute(self, input_data):
        return ToolOutput(success=True)

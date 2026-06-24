"""ApprovalTool — determine approval levels and record approval decisions."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class ApprovalCheckInput(ToolInput):
    document_id: str
    amount: float
    business_profile: str
    current_approval_level: int = 0
    approver_id: Optional[str] = None
    decision: Optional[str] = None  # APPROVED | REJECTED | HOLD
    rejection_reason: Optional[str] = None
    tenant_id: str = "default"


class ApprovalCheckOutput(ToolOutput):
    approval_required: bool = True
    levels_required: int = 1
    current_level: int = 0
    is_fully_approved: bool = False
    next_approver_role: Optional[str] = None
    decision_recorded: bool = False
    rejection_reason: Optional[str] = None
    sla_hours: int = 24
    error_code: Optional[str] = None


class ApprovalTool(BaseTool[ApprovalCheckInput, ApprovalCheckOutput]):
    name: ClassVar[str] = "approval"
    description: ClassVar[str] = "Determine approval requirements and record approval decisions"
    input_model: ClassVar = ApprovalCheckInput
    output_model: ClassVar = ApprovalCheckOutput

    def _execute(self, input_data: ApprovalCheckInput) -> ApprovalCheckOutput:
        from core.config.platform_config import get_platform_config
        cfg = get_platform_config().get_tenant_config(input_data.tenant_id).approval

        amount = input_data.amount
        levels = 1
        role = "AP_TEAM"

        for band in cfg.default_matrix:
            max_amt = band.get("max_amount")
            if max_amt is None or amount <= max_amt:
                levels = band.get("levels", 1)
                role = band.get("role", "AP_TEAM")
                break

        current = input_data.current_approval_level
        decision_recorded = False

        if input_data.decision and input_data.approver_id:
            if input_data.decision == "APPROVED":
                current += 1
                decision_recorded = True
            elif input_data.decision == "REJECTED":
                return ApprovalCheckOutput(
                    success=True,
                    approval_required=True,
                    levels_required=levels,
                    current_level=current,
                    is_fully_approved=False,
                    decision_recorded=True,
                    rejection_reason=input_data.rejection_reason,
                )

        is_fully_approved = current >= levels

        sla = cfg.l1_sla_hours if levels == 1 else cfg.l2_sla_hours

        return ApprovalCheckOutput(
            success=True,
            approval_required=True,
            levels_required=levels,
            current_level=current,
            is_fully_approved=is_fully_approved,
            next_approver_role=role if not is_fully_approved else None,
            decision_recorded=decision_recorded,
            sla_hours=sla,
        )

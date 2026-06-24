"""AmountValidationTool — validate invoice amounts against thresholds and approvals."""
from __future__ import annotations

from typing import ClassVar, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class AmountValidationInput(ToolInput):
    total_amount: float
    currency: str = "INR"
    min_amount: float = 1.0
    max_amount: Optional[float] = None
    auto_approve_threshold: Optional[float] = None
    tenant_id: str = "default"
    document_id: Optional[str] = None


class AmountValidationOutput(ToolOutput):
    is_valid: bool = False
    amount_band: str = "UNKNOWN"
    requires_l1_approval: bool = True
    requires_l2_approval: bool = False
    requires_l3_approval: bool = False
    auto_approvable: bool = False
    errors: list = []


class AmountValidationTool(BaseTool[AmountValidationInput, AmountValidationOutput]):
    name: ClassVar[str] = "amount_validation"
    description: ClassVar[str] = "Validate invoice amount and determine required approval levels"
    input_model: ClassVar = AmountValidationInput
    output_model: ClassVar = AmountValidationOutput

    def _execute(self, input_data: AmountValidationInput) -> AmountValidationOutput:
        from core.config.platform_config import get_platform_config
        cfg = get_platform_config().get_tenant_config(input_data.tenant_id)

        amount = input_data.total_amount
        errors = []

        if amount < input_data.min_amount:
            errors.append(f"Amount {amount} is below minimum {input_data.min_amount}")
        if input_data.max_amount and amount > input_data.max_amount:
            errors.append(f"Amount {amount} exceeds maximum {input_data.max_amount}")

        is_valid = not errors

        # Determine approval levels from config matrix
        levels_needed = 3
        for band in cfg.approval.default_matrix:
            max_amt = band.get("max_amount")
            if max_amt is None or amount <= max_amt:
                levels_needed = band.get("levels", 1)
                break

        auto_approve_threshold = input_data.auto_approve_threshold or cfg.matching.auto_approve_threshold
        auto_approvable = is_valid and amount <= auto_approve_threshold

        if amount <= 10_000:
            band = "LOW"
        elif amount <= 100_000:
            band = "MEDIUM"
        elif amount <= 500_000:
            band = "HIGH"
        else:
            band = "VERY_HIGH"

        return AmountValidationOutput(
            success=True,
            is_valid=is_valid,
            amount_band=band,
            requires_l1_approval=levels_needed >= 1,
            requires_l2_approval=levels_needed >= 2,
            requires_l3_approval=levels_needed >= 3,
            auto_approvable=auto_approvable,
            errors=errors,
        )

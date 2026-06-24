"""ArithmeticTool — validate invoice arithmetic (line items, totals, taxes)."""
from __future__ import annotations

from typing import ClassVar, Dict, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class ArithmeticValidationInput(ToolInput):
    line_items: List[Dict]  # [{quantity, unit_price, total, gst_rate, discount}]
    declared_subtotal: Optional[float] = None
    declared_tax_amount: Optional[float] = None
    declared_total: Optional[float] = None
    tolerance_percent: float = 0.01
    document_id: Optional[str] = None


class ArithmeticError(ToolInput):
    field: str
    expected: float
    actual: float
    variance_amount: float
    variance_percent: float


class ArithmeticValidationOutput(ToolOutput):
    is_valid: bool = False
    calculated_subtotal: float = 0.0
    calculated_tax: float = 0.0
    calculated_total: float = 0.0
    errors: List[ArithmeticError] = []
    line_item_errors: List[Dict] = []
    tolerance_used: float = 0.0


class ArithmeticTool(BaseTool[ArithmeticValidationInput, ArithmeticValidationOutput]):
    name: ClassVar[str] = "arithmetic_validation"
    description: ClassVar[str] = "Validate invoice arithmetic: line item totals, subtotals, taxes, and grand total"
    input_model: ClassVar = ArithmeticValidationInput
    output_model: ClassVar = ArithmeticValidationOutput

    def _execute(self, input_data: ArithmeticValidationInput) -> ArithmeticValidationOutput:
        tol = input_data.tolerance_percent / 100.0
        errors = []
        line_errors = []

        # Validate each line item
        calc_subtotal = 0.0
        calc_tax = 0.0
        for i, li in enumerate(input_data.line_items):
            qty = li.get("quantity") or 0.0
            price = li.get("unit_price") or 0.0
            gst_rate = (li.get("gst_rate") or 0.0) / 100.0
            discount = (li.get("discount") or 0.0) / 100.0
            declared_line_total = li.get("total")

            expected_line = qty * price * (1 - discount)
            line_gst = expected_line * gst_rate
            calc_subtotal += expected_line
            calc_tax += line_gst

            if declared_line_total is not None and declared_line_total > 0:
                variance = abs(expected_line - declared_line_total)
                if expected_line > 0 and (variance / expected_line) > tol:
                    line_errors.append({
                        "line": i + 1,
                        "expected": round(expected_line, 2),
                        "declared": round(declared_line_total, 2),
                        "variance": round(variance, 2),
                    })

        calc_total = calc_subtotal + calc_tax

        def check(field, expected, declared):
            if declared is None or declared == 0:
                return
            variance_amt = abs(expected - declared)
            if expected > 0:
                variance_pct = variance_amt / expected
                if variance_pct > tol:
                    errors.append(ArithmeticError(
                        field=field,
                        expected=round(expected, 2),
                        actual=round(declared, 2),
                        variance_amount=round(variance_amt, 2),
                        variance_percent=round(variance_pct * 100, 4),
                    ))

        check("subtotal", calc_subtotal, input_data.declared_subtotal)
        check("tax_amount", calc_tax, input_data.declared_tax_amount)
        check("total_amount", calc_total, input_data.declared_total)

        is_valid = not errors and not line_errors

        return ArithmeticValidationOutput(
            success=True,
            is_valid=is_valid,
            calculated_subtotal=round(calc_subtotal, 2),
            calculated_tax=round(calc_tax, 2),
            calculated_total=round(calc_total, 2),
            errors=errors,
            line_item_errors=line_errors,
            tolerance_used=input_data.tolerance_percent,
        )

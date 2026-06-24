"""LineItemValidationTool — validate invoice line items for completeness and consistency."""
from __future__ import annotations

from typing import ClassVar, Dict, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class LineItemValidationInput(ToolInput):
    line_items: List[Dict]
    document_id: Optional[str] = None
    min_required: int = 1
    validate_hsn: bool = True


class LineItemIssue(ToolInput):
    line_number: int
    field: str
    issue: str
    severity: str = "MEDIUM"


class LineItemValidationOutput(ToolOutput):
    is_valid: bool = False
    total_lines: int = 0
    valid_lines: int = 0
    issues: List[LineItemIssue] = []


class LineItemValidationTool(BaseTool[LineItemValidationInput, LineItemValidationOutput]):
    name: ClassVar[str] = "line_item_validation"
    description: ClassVar[str] = "Validate completeness and consistency of invoice line items"
    input_model: ClassVar = LineItemValidationInput
    output_model: ClassVar = LineItemValidationOutput

    def _execute(self, input_data: LineItemValidationInput) -> LineItemValidationOutput:
        items = input_data.line_items
        issues: List[LineItemIssue] = []
        valid_count = 0

        if len(items) < input_data.min_required:
            return LineItemValidationOutput(
                success=True, is_valid=False, total_lines=len(items), valid_lines=0,
                issues=[LineItemIssue(
                    line_number=0, field="line_items", severity="HIGH",
                    issue=f"Expected at least {input_data.min_required} line items, found {len(items)}",
                )],
            )

        for i, li in enumerate(items):
            line_num = i + 1
            line_valid = True

            if not li.get("description"):
                issues.append(LineItemIssue(line_number=line_num, field="description", issue="Description is missing"))
                line_valid = False

            qty = li.get("quantity")
            if qty is not None and float(qty) <= 0:
                issues.append(LineItemIssue(line_number=line_num, field="quantity", issue=f"Quantity {qty} must be > 0"))
                line_valid = False

            price = li.get("unit_price")
            if price is not None and float(price) < 0:
                issues.append(LineItemIssue(line_number=line_num, field="unit_price", issue=f"Unit price {price} cannot be negative"))
                line_valid = False

            if line_valid:
                valid_count += 1

        return LineItemValidationOutput(
            success=True,
            is_valid=len(issues) == 0,
            total_lines=len(items),
            valid_lines=valid_count,
            issues=issues,
        )

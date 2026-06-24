"""DateValidationTool — validate invoice and due dates."""
from __future__ import annotations

from datetime import datetime, date, timezone
from typing import ClassVar, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class DateValidationInput(ToolInput):
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    posting_date: Optional[str] = None
    max_age_days: int = 365
    max_future_days: int = 30
    document_id: Optional[str] = None


class DateValidationOutput(ToolOutput):
    invoice_date_valid: bool = True
    due_date_valid: bool = True
    invoice_age_days: Optional[int] = None
    is_stale: bool = False
    is_future_dated: bool = False
    errors: list = []


class DateValidationTool(BaseTool[DateValidationInput, DateValidationOutput]):
    name: ClassVar[str] = "date_validation"
    description: ClassVar[str] = "Validate invoice and due dates against business rules"
    input_model: ClassVar = DateValidationInput
    output_model: ClassVar = DateValidationOutput

    def _execute(self, input_data: DateValidationInput) -> DateValidationOutput:
        today = date.today()
        errors = []
        invoice_date_valid = True
        due_date_valid = True
        age_days = None
        is_stale = False
        is_future = False

        if input_data.invoice_date:
            try:
                inv_date = datetime.strptime(input_data.invoice_date, "%Y-%m-%d").date()
                age_days = (today - inv_date).days
                if age_days > input_data.max_age_days:
                    is_stale = True
                    invoice_date_valid = False
                    errors.append(f"Invoice is {age_days} days old (limit: {input_data.max_age_days})")
                elif age_days < -input_data.max_future_days:
                    is_future = True
                    invoice_date_valid = False
                    errors.append(f"Invoice is dated {abs(age_days)} days in the future")
            except ValueError:
                invoice_date_valid = False
                errors.append(f"Invoice date '{input_data.invoice_date}' is not in YYYY-MM-DD format")

        if input_data.due_date:
            try:
                datetime.strptime(input_data.due_date, "%Y-%m-%d")
            except ValueError:
                due_date_valid = False
                errors.append(f"Due date '{input_data.due_date}' is not in YYYY-MM-DD format")

        return DateValidationOutput(
            success=True,
            invoice_date_valid=invoice_date_valid,
            due_date_valid=due_date_valid,
            invoice_age_days=age_days,
            is_stale=is_stale,
            is_future_dated=is_future,
            errors=errors,
        )

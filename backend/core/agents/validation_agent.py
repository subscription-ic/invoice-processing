"""
UniversalValidationAgent — validate all extracted invoice fields.

Populates state.validation.errors and state.validation.is_valid.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, List, Optional

from core.base.agent import BaseAgent
from core.state.workflow_state import ValidationError, WorkflowState


class UniversalValidationAgent(BaseAgent):
    name: ClassVar[str] = "universal_validation_agent"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.validation.gst_tool import GSTTool, GSTValidationInput
        from app.tools.validation.arithmetic_tool import ArithmeticTool, ArithmeticValidationInput
        from app.tools.validation.date_validation_tool import DateValidationTool, DateValidationInput
        from app.tools.validation.duplicate_tool import DuplicateTool, DuplicateCheckInput
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

        gst_tool = GSTTool()
        arith_tool = ArithmeticTool()
        date_tool = DateValidationTool()
        dup_tool = DuplicateTool()
        audit_tool = AuditTool()

        inv = state.invoice
        doc_id = state.workflow.document_id
        tenant_id = state.workflow.tenant_id
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []

        # GSTIN validation
        if inv.vendor_gstin:
            gst_result = gst_tool.run(GSTValidationInput(gstin=inv.vendor_gstin, document_id=doc_id))
            if not gst_result.is_valid:
                errors.append(ValidationError(
                    field="vendor_gstin",
                    rule="GST_FORMAT",
                    message=gst_result.error_detail or "Invalid GSTIN",
                    severity="ERROR",
                    actual_value=inv.vendor_gstin,
                ))

        # Arithmetic validation
        line_items_data = [
            {
                "description": li.description,
                "quantity": float(li.quantity) if li.quantity else None,
                "unit_price": float(li.unit_price) if li.unit_price else None,
                "total": float(li.total) if li.total else None,
            }
            for li in (inv.line_items or [])
        ]
        arith_result = arith_tool.run(ArithmeticValidationInput(
            line_items=line_items_data,
            declared_subtotal=float(inv.subtotal) if inv.subtotal else None,
            declared_tax_amount=float(inv.tax_amount) if inv.tax_amount else None,
            declared_total=float(inv.total_amount) if inv.total_amount else None,
        ))
        for e in arith_result.errors:
            errors.append(ValidationError(
                field=e.field,
                rule="ARITHMETIC",
                message=f"Expected {e.expected}, got {e.actual}",
                severity="ERROR",
            ))

        # Date validation
        date_result = date_tool.run(DateValidationInput(
            invoice_date=str(inv.invoice_date) if inv.invoice_date else None,
            due_date=str(inv.due_date) if inv.due_date else None,
        ))
        for msg in date_result.errors:
            warnings.append(ValidationError(
                field="invoice_date",
                rule="DATE_VALIDATION",
                message=msg,
                severity="WARNING",
            ))

        # Duplicate check
        if inv.invoice_number and inv.vendor_name and inv.total_amount:
            dup_result = dup_tool.run(DuplicateCheckInput(
                invoice_number=inv.invoice_number,
                vendor_name=inv.vendor_name,
                total_amount=float(inv.total_amount),
                file_hash=state.document.file_hash,
                tenant_id=tenant_id,
                document_id=doc_id,
            ))
            if dup_result.is_duplicate:
                errors.append(ValidationError(
                    rule="DUPLICATE_INVOICE",
                    message=f"Duplicate of document {dup_result.duplicate_document_id}",
                    severity="ERROR",
                    error_code="DUPLICATE",
                ))

        is_valid = len(errors) == 0

        audit_tool.run(AuditEventInput(
            document_id=doc_id,
            entity_type="DOCUMENT",
            entity_id=doc_id,
            action="VALIDATION_COMPLETED",
            agent_name=self.name,
            after_state={"is_valid": is_valid, "error_count": len(errors), "warning_count": len(warnings)},
            stage="UNIVERSAL_VALIDATION",
        ))

        new_validation = state.validation.model_copy(update={
            "is_valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "arithmetic_check": {"passed": arith_result.is_valid},
            "duplicate_check": {"is_duplicate": any(e.error_code == "DUPLICATE" for e in errors)},
        })

        new_status = "PROCESSING" if is_valid else "EXCEPTION"

        return state.model_copy(deep=True, update={
            "validation": new_validation,
            "workflow": state.workflow.model_copy(update={
                "status": new_status,
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

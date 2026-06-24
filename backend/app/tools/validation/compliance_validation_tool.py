"""ComplianceValidationTool — validate regulatory compliance (GST filing, e-invoicing)."""
from __future__ import annotations

import re
from typing import ClassVar, Dict, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class ComplianceValidationInput(ToolInput):
    vendor_gstin: Optional[str] = None
    buyer_gstin: Optional[str] = None
    invoice_number: Optional[str] = None
    total_amount: Optional[float] = None
    irn_number: Optional[str] = None
    qr_code_present: bool = False
    document_id: Optional[str] = None
    tenant_id: str = "default"


class ComplianceIssue(ToolInput):
    rule: str
    severity: str = "HIGH"
    message: str = ""
    regulation: str = ""


class ComplianceValidationOutput(ToolOutput):
    is_compliant: bool = False
    issues: List[ComplianceIssue] = []
    e_invoice_required: bool = False
    e_invoice_present: bool = False


_E_INVOICE_THRESHOLD = 5_000_000  # 50 Lakh INR


class ComplianceValidationTool(BaseTool[ComplianceValidationInput, ComplianceValidationOutput]):
    name: ClassVar[str] = "compliance_validation"
    description: ClassVar[str] = "Validate GST compliance, e-invoicing requirements, and regulatory rules"
    input_model: ClassVar = ComplianceValidationInput
    output_model: ClassVar = ComplianceValidationOutput

    def _execute(self, input_data: ComplianceValidationInput) -> ComplianceValidationOutput:
        issues: List[ComplianceIssue] = []

        # e-Invoice threshold check (India: mandatory above 5 Cr turnover)
        e_invoice_required = bool(
            input_data.total_amount and input_data.total_amount >= _E_INVOICE_THRESHOLD
        )
        e_invoice_present = bool(input_data.irn_number)

        if e_invoice_required and not e_invoice_present:
            issues.append(ComplianceIssue(
                rule="E_INVOICE_REQUIRED",
                severity="HIGH",
                message="Invoice Reference Number (IRN) is required for invoices above ₹5 Cr",
                regulation="CBIC Notification 61/2020-CT",
            ))

        # GSTIN format basic check
        if input_data.vendor_gstin:
            if len(input_data.vendor_gstin.replace(" ", "")) != 15:
                issues.append(ComplianceIssue(
                    rule="GSTIN_FORMAT",
                    severity="HIGH",
                    message="Vendor GSTIN format is invalid",
                    regulation="GST Act 2017",
                ))

        return ComplianceValidationOutput(
            success=True,
            is_compliant=len(issues) == 0,
            issues=issues,
            e_invoice_required=e_invoice_required,
            e_invoice_present=e_invoice_present,
        )

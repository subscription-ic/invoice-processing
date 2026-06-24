"""ProfileValidationTool — validate invoice fields against business profile rules."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

import yaml

from core.base.tool import BaseTool, ToolInput, ToolOutput

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


class ProfileValidationInput(ToolInput):
    business_profile: str
    invoice_data: Dict[str, Any]
    document_id: str
    tenant_id: str = "default"
    model: Optional[str] = None


class ProfileValidationIssue(ToolInput):
    field: str
    rule: str
    severity: str = "HIGH"
    message: str = ""


class ProfileValidationOutput(ToolOutput):
    is_valid: bool = False
    profile_applied: Optional[str] = None
    issues: List[ProfileValidationIssue] = []
    mandatory_fields_present: bool = True
    conditional_fields_satisfied: bool = True
    error_code: Optional[str] = None


# Profile-specific mandatory field requirements
_PROFILE_RULES: Dict[str, Dict] = {
    "PO_RAW_MATERIAL": {
        "mandatory": ["invoice_number", "vendor_name", "po_number", "total_amount", "invoice_date"],
        "requires_grn": True,
    },
    "NON_PO_RAW_MATERIAL": {
        "mandatory": ["invoice_number", "vendor_name", "total_amount", "invoice_date"],
        "requires_grn": False,
    },
    "PO_CAPEX": {
        "mandatory": ["invoice_number", "vendor_name", "po_number", "total_amount", "invoice_date"],
        "requires_grn": True,
    },
    "NON_PO_CAPEX": {
        "mandatory": ["invoice_number", "vendor_name", "total_amount", "invoice_date"],
        "requires_grn": False,
    },
    "PO_OPEX": {
        "mandatory": ["invoice_number", "vendor_name", "po_number", "total_amount", "invoice_date"],
        "requires_grn": False,
    },
    "NON_PO_OPEX": {
        "mandatory": ["invoice_number", "vendor_name", "total_amount", "invoice_date"],
        "requires_grn": False,
    },
    "LEASE_RENT": {
        "mandatory": ["invoice_number", "vendor_name", "total_amount", "invoice_date"],
        "requires_grn": False,
    },
    "EMPLOYEE_REIMBURSEMENT": {
        "mandatory": ["invoice_number", "total_amount", "invoice_date"],
        "requires_grn": False,
    },
    "PETTY_CASH": {
        "mandatory": ["total_amount", "invoice_date"],
        "requires_grn": False,
    },
}


class ProfileValidationTool(BaseTool[ProfileValidationInput, ProfileValidationOutput]):
    name: ClassVar[str] = "profile_validation"
    description: ClassVar[str] = "Validate invoice fields against business profile-specific rules"
    input_model: ClassVar = ProfileValidationInput
    output_model: ClassVar = ProfileValidationOutput

    def _execute(self, input_data: ProfileValidationInput) -> ProfileValidationOutput:
        profile = input_data.business_profile
        rules = _PROFILE_RULES.get(profile, _PROFILE_RULES["NON_PO_OPEX"])
        data = input_data.invoice_data
        issues = []
        mandatory_ok = True
        conditional_ok = True

        # Mandatory field check
        for field in rules.get("mandatory", []):
            val = data.get(field)
            if not val or (isinstance(val, str) and not val.strip()):
                mandatory_ok = False
                issues.append(ProfileValidationIssue(
                    field=field,
                    rule="MANDATORY_FIELD_MISSING",
                    severity="HIGH",
                    message=f"Mandatory field '{field}' is missing or empty for profile {profile}",
                ))

        # PO number required for PO profiles
        if profile.startswith("PO_") and not data.get("po_number"):
            conditional_ok = False
            issues.append(ProfileValidationIssue(
                field="po_number",
                rule="PO_REFERENCE_REQUIRED",
                severity="HIGH",
                message=f"Profile {profile} requires a Purchase Order reference number",
            ))

        # GRN required for certain profiles
        if rules.get("requires_grn") and not data.get("grn_number"):
            issues.append(ProfileValidationIssue(
                field="grn_number",
                rule="GRN_REFERENCE_REQUIRED",
                severity="MEDIUM",
                message=f"Profile {profile} typically requires a GRN reference",
            ))

        is_valid = mandatory_ok and conditional_ok

        return ProfileValidationOutput(
            success=True,
            is_valid=is_valid,
            profile_applied=profile,
            issues=issues,
            mandatory_fields_present=mandatory_ok,
            conditional_fields_satisfied=conditional_ok,
        )

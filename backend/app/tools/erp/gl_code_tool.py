"""GLCodeTool — look up GL codes by business profile and category."""
from __future__ import annotations

from typing import ClassVar, Dict, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


# Default GL code mapping per business profile
_GL_MAP: Dict[str, Dict[str, str]] = {
    "PO_RAW_MATERIAL":      {"expense": "5001", "tax": "1401", "ap": "2001"},
    "NON_PO_RAW_MATERIAL":  {"expense": "5001", "tax": "1401", "ap": "2001"},
    "PO_CAPEX":             {"expense": "1200", "tax": "1401", "ap": "2001"},
    "NON_PO_CAPEX":         {"expense": "1200", "tax": "1401", "ap": "2001"},
    "PO_OPEX":              {"expense": "6001", "tax": "1401", "ap": "2001"},
    "NON_PO_OPEX":          {"expense": "6001", "tax": "1401", "ap": "2001"},
    "LEASE_RENT":           {"expense": "6100", "tax": "1401", "ap": "2001"},
    "EMPLOYEE_REIMBURSEMENT": {"expense": "7001", "tax": "1401", "ap": "2001"},
    "PETTY_CASH":           {"expense": "7100", "tax": "1401", "ap": "2001"},
}


class GLCodeInput(ToolInput):
    business_profile: str
    cost_center: Optional[str] = None
    tenant_id: str = "default"


class GLCodeOutput(ToolOutput):
    expense_gl: str = "5001"
    tax_gl: str = "1401"
    ap_gl: str = "2001"
    profile_used: Optional[str] = None


class GLCodeTool(BaseTool[GLCodeInput, GLCodeOutput]):
    name: ClassVar[str] = "gl_code"
    description: ClassVar[str] = "Resolve GL account codes for expense, tax, and AP based on business profile"
    input_model: ClassVar = GLCodeInput
    output_model: ClassVar = GLCodeOutput

    def _execute(self, input_data: GLCodeInput) -> GLCodeOutput:
        codes = _GL_MAP.get(input_data.business_profile, _GL_MAP["NON_PO_OPEX"])
        return GLCodeOutput(
            success=True,
            expense_gl=codes["expense"],
            tax_gl=codes["tax"],
            ap_gl=codes["ap"],
            profile_used=input_data.business_profile,
        )

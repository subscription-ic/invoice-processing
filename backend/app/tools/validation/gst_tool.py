"""GSTTool — validate Indian GST numbers and compute GST amounts."""
from __future__ import annotations

import re
from typing import ClassVar, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput

_GST_PATTERN = re.compile(
    r"^(\d{2})[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$"
)

# State codes 01–37 are valid
_VALID_STATE_CODES = {str(i).zfill(2) for i in range(1, 38)}


class GSTValidationInput(ToolInput):
    gstin: str
    document_id: Optional[str] = None


class GSTValidationOutput(ToolOutput):
    is_valid: bool = False
    gstin_normalized: Optional[str] = None
    state_code: Optional[str] = None
    entity_type: Optional[str] = None
    error_code: Optional[str] = None
    error_detail: Optional[str] = None


class GSTTool(BaseTool[GSTValidationInput, GSTValidationOutput]):
    name: ClassVar[str] = "gst_validation"
    description: ClassVar[str] = "Validate Indian GST Identification Numbers (GSTIN)"
    input_model: ClassVar = GSTValidationInput
    output_model: ClassVar = GSTValidationOutput

    def _execute(self, input_data: GSTValidationInput) -> GSTValidationOutput:
        raw = input_data.gstin.strip().upper()
        normalized = re.sub(r"\s+", "", raw)

        if len(normalized) != 15:
            return GSTValidationOutput(
                success=True, is_valid=False, gstin_normalized=normalized,
                error_code="GST_LENGTH_INVALID",
                error_detail=f"GSTIN must be 15 characters, got {len(normalized)}",
            )

        if not _GST_PATTERN.match(normalized):
            return GSTValidationOutput(
                success=True, is_valid=False, gstin_normalized=normalized,
                error_code="GST_FORMAT_INVALID",
                error_detail="GSTIN does not match the required format: 2-digit state + 10-digit PAN + 1 entity + Z + checksum",
            )

        state_code = normalized[:2]
        if state_code not in _VALID_STATE_CODES:
            return GSTValidationOutput(
                success=True, is_valid=False, gstin_normalized=normalized,
                error_code="GST_INVALID_STATE",
                error_detail=f"State code '{state_code}' is not a valid Indian state code",
            )

        # Determine entity type from character 13 (0-indexed 12)
        entity_char = normalized[12]
        entity_types = {
            "1": "PROPRIETORSHIP", "2": "PARTNERSHIP", "3": "HUF",
            "4": "COMPANY", "5": "PUBLIC", "6": "GOVERNMENT",
            "7": "STATUTORY", "8": "TRUST", "9": "AOP_BOI",
        }
        entity_type = entity_types.get(entity_char, "OTHER")

        return GSTValidationOutput(
            success=True,
            is_valid=True,
            gstin_normalized=normalized,
            state_code=state_code,
            entity_type=entity_type,
        )


class GSTAmountInput(ToolInput):
    base_amount: float
    gst_rate_percent: float
    calculate_reverse: bool = False
    gst_type: str = "CGST_SGST"  # CGST_SGST | IGST


class GSTAmountOutput(ToolOutput):
    base_amount: float = 0.0
    cgst_amount: float = 0.0
    sgst_amount: float = 0.0
    igst_amount: float = 0.0
    total_gst: float = 0.0
    total_amount: float = 0.0


class GSTAmountTool(BaseTool[GSTAmountInput, GSTAmountOutput]):
    name: ClassVar[str] = "gst_amount"
    description: ClassVar[str] = "Calculate GST component amounts from base amount and rate"
    input_model: ClassVar = GSTAmountInput
    output_model: ClassVar = GSTAmountOutput

    def _execute(self, input_data: GSTAmountInput) -> GSTAmountOutput:
        base = input_data.base_amount
        rate = input_data.gst_rate_percent / 100.0

        if input_data.gst_type == "IGST":
            igst = round(base * rate, 2)
            return GSTAmountOutput(
                success=True,
                base_amount=base,
                igst_amount=igst,
                total_gst=igst,
                total_amount=round(base + igst, 2),
            )
        else:
            half_rate = rate / 2
            cgst = round(base * half_rate, 2)
            sgst = round(base * half_rate, 2)
            return GSTAmountOutput(
                success=True,
                base_amount=base,
                cgst_amount=cgst,
                sgst_amount=sgst,
                total_gst=round(cgst + sgst, 2),
                total_amount=round(base + cgst + sgst, 2),
            )

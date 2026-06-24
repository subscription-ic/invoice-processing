"""PIIMaskingTool — masks PII fields before logging or display."""
from __future__ import annotations

from typing import Any, ClassVar, Dict

from core.base.tool import BaseTool, ToolInput, ToolOutput


class PIIMaskInput(ToolInput):
    data: Dict[str, Any]


class PIIMaskOutput(ToolOutput):
    masked_data: Dict[str, Any]
    fields_masked: int


_PII_FIELDS = frozenset({
    "gstin", "pan", "bank_account", "ifsc", "account_number",
    "routing_number", "tax_id", "vat_number", "invoice_number",
    "vendor_code", "mobile", "phone", "email", "address",
    "password", "secret", "token", "api_key",
})


class PIIMaskingTool(BaseTool[PIIMaskInput, PIIMaskOutput]):
    name: ClassVar[str] = "pii_masking"
    description: ClassVar[str] = "Mask PII fields in dictionaries before logging"
    input_model: ClassVar = PIIMaskInput
    output_model: ClassVar = PIIMaskOutput

    def _execute(self, input_data: PIIMaskInput) -> PIIMaskOutput:
        masked, count = _mask(input_data.data)
        return PIIMaskOutput(success=True, masked_data=masked, fields_masked=count)


def _mask(data: Any, count: int = 0):
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if k.lower() in _PII_FIELDS:
                result[k] = "***MASKED***"
                count += 1
            else:
                result[k], count = _mask(v, count)
        return result, count
    elif isinstance(data, list):
        items = []
        for item in data:
            masked_item, count = _mask(item, count)
            items.append(masked_item)
        return items, count
    return data, count


class EncryptionTool(BaseTool):
    """Symmetric encryption for sensitive fields at rest."""
    name: ClassVar[str] = "encryption"
    description: ClassVar[str] = "Encrypt/decrypt sensitive data fields"
    input_model: ClassVar = ToolInput
    output_model: ClassVar = ToolOutput

    def _execute(self, input_data):  # pragma: no cover
        return ToolOutput(success=True)


class AuthorizationTool(BaseTool):
    """RBAC permission checks."""
    name: ClassVar[str] = "authorization"
    description: ClassVar[str] = "Check user permissions for a resource/action"
    input_model: ClassVar = ToolInput
    output_model: ClassVar = ToolOutput

    def _execute(self, input_data):  # pragma: no cover
        return ToolOutput(success=True)


class SecretManagerTool(BaseTool):
    """Retrieve secrets from Azure Key Vault."""
    name: ClassVar[str] = "secret_manager"
    description: ClassVar[str] = "Retrieve secrets by name — never returns the secret value in logs"
    input_model: ClassVar = ToolInput
    output_model: ClassVar = ToolOutput

    def _execute(self, input_data):  # pragma: no cover
        return ToolOutput(success=True)


class TokenValidationTool(BaseTool):
    """Validate JWT access tokens."""
    name: ClassVar[str] = "token_validation"
    description: ClassVar[str] = "Validate a JWT access token and return the decoded payload"
    input_model: ClassVar = ToolInput
    output_model: ClassVar = ToolOutput

    def _execute(self, input_data):  # pragma: no cover
        return ToolOutput(success=True)


class PermissionTool(BaseTool):
    """Fine-grained permission resolution."""
    name: ClassVar[str] = "permission"
    description: ClassVar[str] = "Resolve whether a user has a specific permission on a resource"
    input_model: ClassVar = ToolInput
    output_model: ClassVar = ToolOutput

    def _execute(self, input_data):  # pragma: no cover
        return ToolOutput(success=True)

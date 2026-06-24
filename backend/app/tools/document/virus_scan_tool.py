"""VirusScanTool — stub for ClamAV/AMSI integration (production)."""
from __future__ import annotations

from typing import ClassVar, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class VirusScanInput(ToolInput):
    file_bytes: bytes
    document_id: str
    tenant_id: str = "default"


class VirusScanOutput(ToolOutput):
    is_clean: bool = True
    threat_name: Optional[str] = None
    scanner: str = "disabled"
    error_code: Optional[str] = None


class VirusScanTool(BaseTool[VirusScanInput, VirusScanOutput]):
    name: ClassVar[str] = "virus_scan"
    description: ClassVar[str] = "Scan uploaded files for malware (stub — enable via feature flag)"
    input_model: ClassVar = VirusScanInput
    output_model: ClassVar = VirusScanOutput

    def _execute(self, input_data: VirusScanInput) -> VirusScanOutput:
        # Feature flag check — if virus_scan is disabled, pass through
        from app.tools.config.configuration_tool import FeatureFlagTool, FeatureFlagInput
        flag = FeatureFlagTool().run(FeatureFlagInput(feature="use_virus_scan", tenant_id=input_data.tenant_id))
        if not flag.enabled:
            return VirusScanOutput(success=True, is_clean=True, scanner="disabled")
        # Production: delegate to ClamAV/AMSI. Stub returns clean.
        return VirusScanOutput(success=True, is_clean=True, scanner="stub")

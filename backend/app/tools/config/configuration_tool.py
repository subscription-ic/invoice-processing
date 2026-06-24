"""ConfigurationTool — reads per-tenant config from PlatformConfig."""
from __future__ import annotations

from typing import Any, ClassVar, Optional

from pydantic import Field

from core.base.tool import BaseTool, ToolInput, ToolOutput


class ConfigGetInput(ToolInput):
    key: str
    tenant_id: str = "default"
    default: Optional[Any] = None


class ConfigGetOutput(ToolOutput):
    key: str
    value: Optional[Any]
    tenant_id: str
    found: bool


class ConfigurationTool(BaseTool[ConfigGetInput, ConfigGetOutput]):
    name: ClassVar[str] = "configuration"
    description: ClassVar[str] = "Read per-tenant runtime configuration values"
    input_model: ClassVar = ConfigGetInput
    output_model: ClassVar = ConfigGetOutput

    def _execute(self, input_data: ConfigGetInput) -> ConfigGetOutput:
        from core.config.platform_config import get_platform_config
        cfg = get_platform_config()
        tenant_cfg = cfg.get_tenant_config(input_data.tenant_id)

        # Navigate nested config using dotted key: "ocr.dpi" → tenant_cfg.ocr.dpi
        parts = input_data.key.split(".")
        obj: Any = tenant_cfg
        for part in parts:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            elif isinstance(obj, dict):
                obj = obj.get(part)
            else:
                obj = None
                break

        found = obj is not None
        return ConfigGetOutput(
            success=True,
            key=input_data.key,
            value=obj if found else input_data.default,
            tenant_id=input_data.tenant_id,
            found=found,
        )


class FeatureFlagInput(ToolInput):
    feature: str
    tenant_id: str = "default"


class FeatureFlagOutput(ToolOutput):
    feature: str
    enabled: bool
    tenant_id: str


class FeatureFlagTool(BaseTool[FeatureFlagInput, FeatureFlagOutput]):
    name: ClassVar[str] = "feature_flag"
    description: ClassVar[str] = "Check whether a feature flag is enabled for a tenant"
    input_model: ClassVar = FeatureFlagInput
    output_model: ClassVar = FeatureFlagOutput

    def _execute(self, input_data: FeatureFlagInput) -> FeatureFlagOutput:
        from core.config.platform_config import get_platform_config
        cfg = get_platform_config()
        enabled = cfg.feature_enabled(input_data.feature, input_data.tenant_id)
        return FeatureFlagOutput(
            success=True,
            feature=input_data.feature,
            enabled=enabled,
            tenant_id=input_data.tenant_id,
        )

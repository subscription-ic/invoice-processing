"""
PlatformConfig — runtime configuration loaded from YAML + environment overrides.

Design rules:
- All business rules live in configuration, never in code.
- Every threshold, tolerance, and limit is configurable per tenant.
- Configuration is read-only after load; no mutable global state.
- Secrets are NEVER stored here — use SecretManagerTool for secrets.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-config models
# ---------------------------------------------------------------------------

class UploadConfig(BaseModel):
    max_file_size_mb: int = 50
    allowed_extensions: List[str] = Field(
        default=[".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".docx"]
    )
    allowed_mime_types: List[str] = Field(
        default=[
            "application/pdf",
            "image/jpeg",
            "image/png",
            "image/tiff",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ]
    )
    virus_scan_enabled: bool = False
    max_pages: int = 100


class OCRConfig(BaseModel):
    min_image_quality_threshold: float = 0.4
    min_acceptable_confidence: float = 0.6
    min_word_count: int = 10
    default_language: str = "eng"
    tesseract_config: str = "--oem 3 --psm 6"
    enhancement_enabled: bool = True
    dpi: int = 300


class ExtractionConfig(BaseModel):
    llm_model: str = "gpt-4o"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 4096
    min_field_confidence: float = 0.75
    max_missing_mandatory_fields: int = 2
    token_budget_per_document: int = 8000
    prompt_version: str = "1.0"


class ValidationConfig(BaseModel):
    arithmetic_tolerance_percent: float = 0.01
    date_max_age_days: int = 365
    date_max_future_days: int = 30
    duplicate_check_enabled: bool = True
    duplicate_window_days: int = 90


class MatchingConfig(BaseModel):
    price_tolerance_percent: float = 2.0
    quantity_tolerance_percent: float = 1.0
    tax_tolerance_percent: float = 0.5
    full_match_threshold: float = 0.95
    partial_match_lower: float = 0.70
    partial_match_upper: float = 0.94
    failed_match_threshold: float = 0.69
    auto_approve_threshold: float = 50000.0  # INR


class ConfidenceConfig(BaseModel):
    high_band_threshold: float = 0.85
    medium_band_threshold: float = 0.65
    low_band_threshold: float = 0.45
    # Weight of each component in overall score
    weights: Dict[str, float] = Field(
        default={
            "ocr_confidence": 0.15,
            "extraction_confidence": 0.30,
            "validation_pass": 0.20,
            "profile_confidence": 0.10,
            "match_score": 0.25,
        }
    )


class ApprovalConfig(BaseModel):
    # Default matrix: amount bands → approval levels required
    default_matrix: List[Dict[str, Any]] = Field(
        default=[
            {"max_amount": 10000, "levels": 1, "role": "AP_TEAM"},
            {"max_amount": 100000, "levels": 2, "role": "FINANCE"},
            {"max_amount": 500000, "levels": 2, "role": "APPROVER"},
            {"max_amount": None, "levels": 3, "role": "APPROVER"},
        ]
    )
    l1_sla_hours: int = 24
    l2_sla_hours: int = 48
    escalation_sla_hours: int = 72


class ERPConfig(BaseModel):
    provider: str = "mock"  # mock | sap | oracle | dynamics | netsuite
    allow_mock_in_production: bool = False


class StorageConfig(BaseModel):
    provider: str = "local"  # local | azure_blob | s3
    allow_local_in_production: bool = False
    local_upload_dir: str = "uploads"
    azure_container_name: str = "invoices"


class RetryConfig(BaseModel):
    max_retries: int = 3
    backoff_strategy: str = "EXPONENTIAL_JITTER"  # EXPONENTIAL_JITTER | EXPONENTIAL | LINEAR | FIXED
    base_delay_seconds: int = 2
    max_delay_seconds: int = 120


class NotificationConfig(BaseModel):
    email_enabled: bool = False
    teams_enabled: bool = False
    sms_enabled: bool = False
    default_channels: List[str] = Field(default=["email"])


# ---------------------------------------------------------------------------
# Tenant-level config (per-tenant overrides allowed)
# ---------------------------------------------------------------------------

class TenantConfig(BaseModel):
    """Full configuration for a single tenant."""

    tenant_id: str = "default"
    tenant_name: str = "Default Tenant"
    currency: str = "INR"
    timezone: str = "Asia/Kolkata"
    country_code: str = "IN"

    upload: UploadConfig = Field(default_factory=UploadConfig)
    ocr: OCRConfig = Field(default_factory=OCRConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
    erp: ERPConfig = Field(default_factory=ERPConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)

    # Feature flags for incremental rollout
    features: Dict[str, bool] = Field(
        default={
            "use_langgraph_pipeline": False,   # Phase 4: flip to True
            "use_azure_storage": False,         # Phase 8: flip to True
            "use_confidence_agent": True,
            "use_virus_scan": False,
            "use_token_tracking": True,
        }
    )


# ---------------------------------------------------------------------------
# Platform-level config (across all tenants)
# ---------------------------------------------------------------------------

class PlatformConfig(BaseModel):
    """Top-level platform configuration."""

    environment: str = "development"
    service_name: str = "ap-automation-platform"
    log_level: str = "INFO"
    default_tenant: TenantConfig = Field(default_factory=TenantConfig)
    tenants: Dict[str, TenantConfig] = Field(default_factory=dict)

    def get_tenant_config(self, tenant_id: str = "default") -> TenantConfig:
        """Get configuration for a specific tenant, falling back to default."""
        return self.tenants.get(tenant_id, self.default_tenant)

    def is_production(self) -> bool:
        return self.environment == "production"

    def feature_enabled(self, feature: str, tenant_id: str = "default") -> bool:
        """Check if a feature flag is enabled for a tenant."""
        tenant_cfg = self.get_tenant_config(tenant_id)
        return tenant_cfg.features.get(feature, False)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent / "default.yaml"


def _load_yaml_config(path: Path) -> Dict[str, Any]:
    """Load YAML config file, returning empty dict if not found."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _build_platform_config() -> PlatformConfig:
    """Build PlatformConfig from YAML file + environment variable overrides."""
    data = _load_yaml_config(_CONFIG_PATH)

    # Environment overrides (precedence: env vars > YAML > defaults)
    if env := os.getenv("ENVIRONMENT"):
        data["environment"] = env
    if log_level := os.getenv("LOG_LEVEL"):
        data["log_level"] = log_level

    # Inject ERP provider from env
    if erp_provider := os.getenv("ERP_PROVIDER"):
        data.setdefault("default_tenant", {}).setdefault("erp", {})["provider"] = erp_provider

    # Inject storage provider from env
    if storage_provider := os.getenv("STORAGE_PROVIDER"):
        data.setdefault("default_tenant", {}).setdefault("storage", {})["provider"] = storage_provider

    return PlatformConfig(**data)


@lru_cache(maxsize=1)
def get_platform_config() -> PlatformConfig:
    """Return the global PlatformConfig singleton (cached after first call)."""
    return _build_platform_config()

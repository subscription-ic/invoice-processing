from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # App
    APP_NAME: str = "AP Automation Platform"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Security
    SECRET_KEY: str = "supersecretkey-change-in-production-32chars-minimum"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    ALGORITHM: str = "HS256"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://apuser:appassword@localhost:5432/ap_platform"
    SYNC_DATABASE_URL: str = "postgresql://apuser:appassword@localhost:5432/ap_platform"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 40

    # Redis & Celery
    REDIS_URL: str = "redis://:redispassword@localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://:redispassword@localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://:redispassword@localhost:6379/1"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_VISION_MODEL: str = "gpt-4o"
    OPENAI_MAX_TOKENS: int = 4096
    OPENAI_TEMPERATURE: float = 0.0

    # Storage
    UPLOAD_DIR: str = "/app/uploads"
    MAX_UPLOAD_SIZE_MB: int = 50
    ALLOWED_EXTENSIONS: str = "pdf,jpg,jpeg,png,docx,tiff"

    # Matching tolerances
    PRICE_TOLERANCE_PERCENT: float = 2.0
    QUANTITY_TOLERANCE_PERCENT: float = 0.0
    TAX_TOLERANCE_PERCENT: float = 1.0

    # OCR thresholds
    OCR_CONFIDENCE_PASS: float = 0.85
    OCR_CONFIDENCE_WARNING: float = 0.70

    # Tesseract binary path (Windows). Leave blank to use system PATH.
    TESSERACT_CMD: Optional[str] = None

    # Image quality thresholds
    BLUR_VARIANCE_GOOD: float = 150.0
    BLUR_VARIANCE_WARNING: float = 100.0
    BRIGHTNESS_MIN: float = 40.0
    BRIGHTNESS_MAX: float = 220.0
    SKEW_ANGLE_THRESHOLD: float = 10.0

    # SLA hours by queue
    SLA_AP_TEAM_HOURS: int = 4
    SLA_FINANCE_HOURS: int = 8
    SLA_PROCUREMENT_HOURS: int = 24
    SLA_COMPLIANCE_HOURS: int = 48
    SLA_WAREHOUSE_HOURS: int = 8

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # Future: Azure
    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = None
    AZURE_STORAGE_CONTAINER: str = "documents"
    AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT: Optional[str] = None
    AZURE_DOCUMENT_INTELLIGENCE_KEY: Optional[str] = None

    # Future: Email
    IMAP_HOST: Optional[str] = None
    IMAP_PORT: int = 993
    IMAP_USER: Optional[str] = None
    IMAP_PASSWORD: Optional[str] = None

    # Future: Teams
    TEAMS_TENANT_ID: Optional[str] = None
    TEAMS_CLIENT_ID: Optional[str] = None
    TEAMS_CLIENT_SECRET: Optional[str] = None

    # LangGraph (Phase 4+)
    USE_LANGGRAPH_PIPELINE: bool = False
    DEFAULT_TENANT_ID: str = "default"

    @property
    def allowed_extensions_list(self) -> List[str]:
        return [ext.strip().lower() for ext in self.ALLOWED_EXTENSIONS.split(",")]

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
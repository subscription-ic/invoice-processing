"""
BaseProvider — abstract base class for all external service providers.

Provider types:
- OCRProvider: document text extraction (Tesseract, Azure DI, Google Vision)
- LLMProvider: language model calls (OpenAI, Azure OpenAI, Anthropic)
- ERPProvider: ERP system integration (Mock, SAP, Oracle, Dynamics, NetSuite)
- StorageProvider: file storage (Local, Azure Blob, S3)
- NotificationProvider: message dispatch (Email, Teams, SMS)

Design rules:
- Providers wrap a single external service.
- Swapping providers requires zero changes to agents or tools.
- All providers implement health_check() for startup and monitoring.
- Providers are registered in the DI container; agents/tools never instantiate them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, Optional


class BaseProvider(ABC):
    """Abstract base class for all external service providers."""

    provider_name: ClassVar[str]
    provider_type: ClassVar[str]  # OCR | LLM | ERP | STORAGE | NOTIFICATION

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        logger: Optional[Any] = None,
    ) -> None:
        self._config: Dict[str, Any] = config or {}
        self._logger = logger

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Verify the provider is reachable and healthy.

        Returns True if healthy, False otherwise.
        Should not raise — catch internal exceptions and return False.
        """

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def require_config(self, key: str) -> Any:
        from core.base.exceptions import ConfigurationException

        value = self._config.get(key)
        if value is None:
            raise ConfigurationException(
                f"Required configuration key '{key}' is missing for provider '{self.provider_name}'",
                config_key=key,
            )
        return value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(provider={self.provider_name!r})"

"""
Platform exception hierarchy.

Design rules:
- Every exception carries a machine-readable error_code.
- RetryableException subclasses are eligible for RetryGraph.
- NonRetryableException subclasses halt immediately.
- AgentException wraps tool failures with agent context.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class PlatformException(Exception):
    """Base class for all platform exceptions."""

    def __init__(
        self,
        message: str,
        error_code: str = "PLATFORM_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.error_code!r}, message={self.message!r})"


class RetryableException(PlatformException):
    """
    Exception that indicates the operation may succeed on retry.

    Examples: network timeouts, transient DB errors, LLM rate limits.
    """

    def __init__(
        self,
        message: str,
        error_code: str = "RETRYABLE_ERROR",
        retry_after_seconds: int = 5,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details)
        self.retry_after_seconds = retry_after_seconds


class NonRetryableException(PlatformException):
    """
    Exception that indicates the operation will never succeed on retry.

    Examples: validation failures, duplicate invoices, authorisation errors.
    """


# ---------------------------------------------------------------------------
# Domain-specific exceptions
# ---------------------------------------------------------------------------

class AgentException(PlatformException):
    """Raised when an agent fails to execute."""

    def __init__(
        self,
        message: str,
        agent_name: str,
        error_code: str = "AGENT_ERROR",
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details)
        self.agent_name = agent_name
        self.retryable = retryable


class ToolException(PlatformException):
    """Raised when a tool fails to execute."""

    def __init__(
        self,
        message: str,
        tool_name: str,
        error_code: str = "TOOL_ERROR",
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details)
        self.tool_name = tool_name
        self.retryable = retryable


class RepositoryException(RetryableException):
    """Raised on database access failures."""

    def __init__(
        self,
        message: str,
        entity_type: str,
        operation: str,
        error_code: str = "REPOSITORY_ERROR",
    ) -> None:
        super().__init__(message, error_code)
        self.entity_type = entity_type
        self.operation = operation


class ProviderException(PlatformException):
    """Raised when an external provider (OCR, LLM, ERP, Storage) fails."""

    def __init__(
        self,
        message: str,
        provider_name: str,
        error_code: str = "PROVIDER_ERROR",
        retryable: bool = True,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details)
        self.provider_name = provider_name
        self.retryable = retryable


class ValidationException(NonRetryableException):
    """Raised when input validation fails — never retried."""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        error_code: str = "VALIDATION_ERROR",
    ) -> None:
        super().__init__(message, error_code)
        self.field = field


class ConfigurationException(NonRetryableException):
    """Raised when required configuration is missing or invalid."""

    def __init__(self, message: str, config_key: Optional[str] = None) -> None:
        super().__init__(message, "CONFIGURATION_ERROR")
        self.config_key = config_key


class AuthorizationException(NonRetryableException):
    """Raised when a user lacks required permissions."""

    def __init__(self, message: str, required_permission: Optional[str] = None) -> None:
        super().__init__(message, "AUTHORIZATION_ERROR")
        self.required_permission = required_permission


class DuplicateInvoiceException(NonRetryableException):
    """Raised when a duplicate invoice is detected — workflow halts."""

    def __init__(
        self,
        message: str,
        existing_document_id: str,
        similarity_score: float = 1.0,
    ) -> None:
        super().__init__(message, "DUPLICATE_INVOICE")
        self.existing_document_id = existing_document_id
        self.similarity_score = similarity_score


class ERPPostingException(RetryableException):
    """Raised when ERP posting fails — eligible for retry."""

    def __init__(
        self,
        message: str,
        erp_provider: str,
        error_code: str = "ERP_POSTING_ERROR",
    ) -> None:
        super().__init__(message, error_code)
        self.erp_provider = erp_provider


class TokenBudgetExceededException(NonRetryableException):
    """Raised when a tenant's LLM token budget is exhausted."""

    def __init__(self, tenant_id: str, budget_limit: int, current_usage: int) -> None:
        super().__init__(
            f"Token budget exceeded for tenant {tenant_id}: {current_usage}/{budget_limit}",
            "TOKEN_BUDGET_EXCEEDED",
        )
        self.tenant_id = tenant_id
        self.budget_limit = budget_limit
        self.current_usage = current_usage


class MockInProductionException(NonRetryableException):
    """Raised when mock ERP or local storage is used in a production environment."""

    def __init__(self, component: str) -> None:
        super().__init__(
            f"Mock component '{component}' cannot be used in production. "
            "Check configuration flags.",
            "MOCK_IN_PRODUCTION",
        )
        self.component = component

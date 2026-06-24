"""
BaseTool — abstract base class for all 112 platform tools.

Design rules:
- Tools are stateless: no instance state modified after __init__.
- Tools accept typed ToolInput and return typed ToolOutput.
- All business logic belongs in tools, not agents.
- Tools are independently testable without database or network.
- Tools log via the injected logger — never print() or use module-level loggers.
- Tools NEVER log PII or full invoice content.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, Generic, Optional, Type, TypeVar

from pydantic import BaseModel, ConfigDict

from core.base.exceptions import ToolException


# ---------------------------------------------------------------------------
# Typed I/O models every tool must define
# ---------------------------------------------------------------------------

class ToolInput(BaseModel):
    """Base class for all tool input models."""

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ToolOutput(BaseModel):
    """Base class for all tool output models."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: Optional[float] = None


TInput = TypeVar("TInput", bound=ToolInput)
TOutput = TypeVar("TOutput", bound=ToolOutput)


# ---------------------------------------------------------------------------
# BaseTool
# ---------------------------------------------------------------------------

class BaseTool(ABC, Generic[TInput, TOutput]):
    """
    Abstract base class for all platform tools.

    Every subclass must declare:
      - name (ClassVar[str]): Unique tool identifier, e.g. "file_validation"
      - description (ClassVar[str]): One-line description of the tool's purpose
      - input_model (ClassVar[Type[ToolInput]]): Typed input schema
      - output_model (ClassVar[Type[ToolOutput]]): Typed output schema

    Usage::

        result = tool.run(MyInput(field="value"))
        if result.success:
            use(result.data)
        else:
            handle_error(result.error_code, result.error_message)
    """

    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[Type[ToolInput]]
    output_model: ClassVar[Type[ToolOutput]]

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        logger: Optional[Any] = None,
    ) -> None:
        self._config: Dict[str, Any] = config or {}
        self._logger = logger

    # ---------------------------------------------------------------------------
    # Public interface — always call run(), not _execute() directly
    # ---------------------------------------------------------------------------

    def run(self, input_data: TInput) -> TOutput:
        """
        Execute the tool with timing, structured logging, and error wrapping.

        This method MUST NOT be overridden. Override _execute() instead.
        """
        start = time.perf_counter()
        try:
            result = self._execute(input_data)
            elapsed_ms = (time.perf_counter() - start) * 1000
            result = result.model_copy(update={"duration_ms": elapsed_ms})
            if self._logger:
                self._logger.debug(
                    "tool_executed",
                    tool=self.name,
                    success=result.success,
                    duration_ms=round(elapsed_ms, 2),
                )
            return result
        except ToolException:
            raise
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            if self._logger:
                self._logger.error(
                    "tool_error",
                    tool=self.name,
                    error=str(exc),
                    duration_ms=round(elapsed_ms, 2),
                )
            raise ToolException(
                message=str(exc),
                tool_name=self.name,
                error_code="TOOL_EXECUTION_ERROR",
                retryable=self._is_retryable(exc),
            ) from exc

    # ---------------------------------------------------------------------------
    # Internal — override in subclasses
    # ---------------------------------------------------------------------------

    @abstractmethod
    def _execute(self, input_data: TInput) -> TOutput:
        """
        Implement the tool's business logic here.

        Must return a ToolOutput subclass. Should not catch exceptions —
        the run() wrapper handles all error cases.
        """

    def _is_retryable(self, exc: Exception) -> bool:
        """
        Determine if the exception is transient and safe to retry.

        Override to customise per tool. Default: not retryable.
        """
        return False

    # ---------------------------------------------------------------------------
    # Configuration helpers
    # ---------------------------------------------------------------------------

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a config value by key with an optional default."""
        return self._config.get(key, default)

    def require_config(self, key: str) -> Any:
        """Get a config value, raising ConfigurationException if missing."""
        from core.base.exceptions import ConfigurationException

        value = self._config.get(key)
        if value is None:
            raise ConfigurationException(
                f"Required configuration key '{key}' is missing for tool '{self.name}'",
                config_key=key,
            )
        return value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"

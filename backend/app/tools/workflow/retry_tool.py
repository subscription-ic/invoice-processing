"""RetryTool — centralised retry logic with exponential backoff and jitter."""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Callable, ClassVar, List, Optional, Type

from core.base.tool import BaseTool, ToolInput, ToolOutput


class RetryInput(ToolInput):
    max_retries: int = 3
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 120.0
    backoff_strategy: str = "EXPONENTIAL_JITTER"
    retryable_exceptions: List[str] = []


class RetryOutput(ToolOutput):
    attempts: int = 0
    succeeded: bool = False
    last_error: Optional[str] = None
    total_delay_seconds: float = 0.0


class RetryTool(BaseTool[RetryInput, RetryOutput]):
    name: ClassVar[str] = "retry"
    description: ClassVar[str] = "Execute a callable with configurable retry and backoff"
    input_model: ClassVar = RetryInput
    output_model: ClassVar = RetryOutput

    def _execute(self, input_data: RetryInput) -> RetryOutput:
        # This tool is typically used programmatically via execute_with_retry()
        return RetryOutput(success=True)

    def execute_with_retry(
        self,
        func: Callable,
        max_retries: int = 3,
        base_delay: float = 2.0,
        max_delay: float = 120.0,
        strategy: str = "EXPONENTIAL_JITTER",
        retryable_on: Optional[List[Type[Exception]]] = None,
    ) -> Any:
        """Execute func with retry. Raises on final failure."""
        last_exc = None
        total_delay = 0.0

        for attempt in range(1, max_retries + 2):
            try:
                return func()
            except Exception as exc:
                last_exc = exc
                if retryable_on and not any(isinstance(exc, t) for t in retryable_on):
                    raise
                if attempt > max_retries:
                    raise
                delay = self._compute_delay(attempt, base_delay, max_delay, strategy)
                total_delay += delay
                time.sleep(delay)

        raise last_exc

    def _compute_delay(self, attempt: int, base: float, max_d: float, strategy: str) -> float:
        if strategy == "FIXED":
            return min(base, max_d)
        elif strategy == "LINEAR":
            return min(base * attempt, max_d)
        elif strategy == "EXPONENTIAL":
            return min(base * (2 ** (attempt - 1)), max_d)
        else:  # EXPONENTIAL_JITTER
            exp = min(base * (2 ** (attempt - 1)), max_d)
            return exp * (0.5 + random.random() * 0.5)


class QueueInput(ToolInput):
    document_id: str
    queue: str
    priority: int = 5
    reason: Optional[str] = None
    metadata: dict = {}


class QueueOutput(ToolOutput):
    queued: bool = False
    queue_name: Optional[str] = None
    queue_id: Optional[str] = None
    error_code: Optional[str] = None


class QueueTool(BaseTool[QueueInput, QueueOutput]):
    name: ClassVar[str] = "queue"
    description: ClassVar[str] = "Route a document to the appropriate exception or review queue"
    input_model: ClassVar = QueueInput
    output_model: ClassVar = QueueOutput

    def _execute(self, input_data: QueueInput) -> QueueOutput:
        import uuid
        return QueueOutput(
            success=True,
            queued=True,
            queue_name=input_data.queue,
            queue_id=str(uuid.uuid4()),
        )

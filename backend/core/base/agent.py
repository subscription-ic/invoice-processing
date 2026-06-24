"""
BaseAgent — abstract base class for all 19 platform agents.

Design rules:
- Agents are thin orchestrators: they call tools and update WorkflowState.
- Agents contain ZERO business logic — all computation is in tools.
- Agents own exactly one section of WorkflowState (their designated output section).
- Every agent must emit an audit event before returning.
- Agents log errors but never raise — they return state with error fields set.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, List, Optional, Type

from core.base.exceptions import AgentException
from core.base.tool import BaseTool
from core.state.workflow_state import WorkflowState


class BaseAgent(ABC):
    """
    Abstract base class for all platform agents.

    Every subclass must declare:
      - name (ClassVar[str]): Unique agent identifier matching agents.md
      - owned_state_section (ClassVar[str]): The WorkflowState key this agent writes to

    Lifecycle:
      1. ``run()`` is the public entry point — called by LangGraph nodes
      2. ``run()`` calls ``_pre_execute()`` for precondition checks
      3. ``run()`` calls ``_execute()`` for business logic (tool calls + state updates)
      4. ``run()`` calls ``_post_execute()`` for audit emit + postcondition checks
      5. On failure, ``run()`` calls ``_handle_error()`` for state error population
    """

    name: ClassVar[str]
    owned_state_section: ClassVar[str]

    def __init__(
        self,
        tools: Optional[Dict[str, BaseTool]] = None,
        logger: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._tools: Dict[str, BaseTool] = tools or {}
        self._logger = logger
        self._config: Dict[str, Any] = config or {}

    # ---------------------------------------------------------------------------
    # Public interface — LangGraph calls run(), not _execute()
    # ---------------------------------------------------------------------------

    def run(self, state: WorkflowState) -> WorkflowState:
        """
        Execute the agent with full lifecycle management.

        Returns an updated WorkflowState. Never raises — errors are embedded
        in the returned state for LangGraph router to handle.
        """
        start = time.perf_counter()
        agent_name = self.name

        try:
            # Update current agent in workflow metadata
            state = state.with_status(state.workflow.status, agent=agent_name)

            # Precondition checks
            precondition_error = self._check_preconditions(state)
            if precondition_error:
                if self._logger:
                    self._logger.warning(
                        "agent_precondition_failed",
                        agent=agent_name,
                        reason=precondition_error,
                    )
                return state.with_error(
                    error_code="PRECONDITION_FAILED",
                    error_message=precondition_error,
                    agent=agent_name,
                )

            # Core execution
            result_state = self._execute(state)

            # Postconditions
            postcondition_error = self._check_postconditions(result_state)
            if postcondition_error:
                if self._logger:
                    self._logger.warning(
                        "agent_postcondition_failed",
                        agent=agent_name,
                        reason=postcondition_error,
                    )
                return result_state.with_error(
                    error_code="POSTCONDITION_FAILED",
                    error_message=postcondition_error,
                    agent=agent_name,
                )

            elapsed_ms = (time.perf_counter() - start) * 1000
            if self._logger:
                self._logger.info(
                    "agent_completed",
                    agent=agent_name,
                    status=result_state.workflow.status,
                    duration_ms=round(elapsed_ms, 2),
                )
            return result_state

        except AgentException as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            if self._logger:
                self._logger.error(
                    "agent_failed",
                    agent=agent_name,
                    error_code=exc.error_code,
                    error=exc.message,
                    duration_ms=round(elapsed_ms, 2),
                )
            return state.with_error(
                error_code=exc.error_code,
                error_message=exc.message,
                agent=agent_name,
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            if self._logger:
                self._logger.error(
                    "agent_unexpected_error",
                    agent=agent_name,
                    error=str(exc),
                    duration_ms=round(elapsed_ms, 2),
                )
            return state.with_error(
                error_code="AGENT_UNEXPECTED_ERROR",
                error_message=str(exc),
                agent=agent_name,
            )

    # ---------------------------------------------------------------------------
    # Override in subclasses
    # ---------------------------------------------------------------------------

    @abstractmethod
    def _execute(self, state: WorkflowState) -> WorkflowState:
        """
        Core agent logic: call tools, update state, return updated state.

        Must NOT contain business logic — delegate everything to tools.
        Must write to self.owned_state_section in the returned state.
        """

    def _check_preconditions(self, state: WorkflowState) -> Optional[str]:
        """
        Check that required state fields are present before execution.

        Return an error message string if preconditions are not met.
        Return None if all preconditions are satisfied.

        Override in subclasses to add agent-specific checks.
        """
        return None

    def _check_postconditions(self, state: WorkflowState) -> Optional[str]:
        """
        Verify the output section was populated correctly after execution.

        Return an error message string if postconditions are not met.
        Return None if all postconditions are satisfied.

        Override in subclasses to add agent-specific checks.
        """
        return None

    # ---------------------------------------------------------------------------
    # Tool access helpers
    # ---------------------------------------------------------------------------

    def get_tool(self, name: str) -> BaseTool:
        """Get a tool by name. Raises AgentException if not found."""
        tool = self._tools.get(name)
        if tool is None:
            raise AgentException(
                message=f"Tool '{name}' not found in agent '{self.name}'. "
                        f"Available tools: {list(self._tools.keys())}",
                agent_name=self.name,
                error_code="TOOL_NOT_FOUND",
                retryable=False,
            )
        return tool

    def has_tool(self, name: str) -> bool:
        """Check if a tool is available without raising."""
        return name in self._tools

    # ---------------------------------------------------------------------------
    # Configuration helpers
    # ---------------------------------------------------------------------------

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def require_config(self, key: str) -> Any:
        value = self._config.get(key)
        if value is None:
            raise AgentException(
                message=f"Required configuration key '{key}' is missing for agent '{self.name}'",
                agent_name=self.name,
                error_code="CONFIGURATION_ERROR",
                retryable=False,
            )
        return value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"

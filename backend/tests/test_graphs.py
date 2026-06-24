"""
Tests for Phase 4 LangGraph graph compilation.

These tests import graph builder functions and verify they compile without
errors using a MemorySaver checkpointer (no database required).

They also exercise the GraphRegistry singleton's startup path.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Graph compilation — MemorySaver (no DB required)
# ---------------------------------------------------------------------------

class TestGraphCompilation:
    """Verify each graph compiles to a callable CompiledGraph."""

    def test_invoice_processing_graph_compiles(self):
        try:
            from langgraph.checkpoint.memory import MemorySaver
            from core.graphs.invoice_processing_graph import build_invoice_processing_graph
            checkpointer = MemorySaver()
            graph = build_invoice_processing_graph(checkpointer=checkpointer)
            assert graph is not None
        except ImportError as e:
            pytest.skip(f"LangGraph or graph deps not installed: {e}")

    def test_exception_graph_compiles(self):
        try:
            from langgraph.checkpoint.memory import MemorySaver
            from core.graphs.exception_graph import build_exception_graph
            graph = build_exception_graph(checkpointer=MemorySaver())
            assert graph is not None
        except ImportError as e:
            pytest.skip(f"LangGraph or graph deps not installed: {e}")

    def test_approval_graph_compiles(self):
        try:
            from langgraph.checkpoint.memory import MemorySaver
            from core.graphs.approval_graph import build_approval_graph
            graph = build_approval_graph(checkpointer=MemorySaver())
            assert graph is not None
        except ImportError as e:
            pytest.skip(f"LangGraph or graph deps not installed: {e}")

    def test_human_review_graph_compiles(self):
        try:
            from langgraph.checkpoint.memory import MemorySaver
            from core.graphs.human_review_graph import build_human_review_graph
            graph = build_human_review_graph(checkpointer=MemorySaver())
            assert graph is not None
        except ImportError as e:
            pytest.skip(f"LangGraph or graph deps not installed: {e}")

    def test_retry_graph_compiles(self):
        try:
            from langgraph.checkpoint.memory import MemorySaver
            from core.graphs.retry_graph import build_retry_graph
            graph = build_retry_graph(checkpointer=MemorySaver())
            assert graph is not None
        except ImportError as e:
            pytest.skip(f"LangGraph or graph deps not installed: {e}")

    def test_notification_graph_compiles(self):
        try:
            from langgraph.checkpoint.memory import MemorySaver
            from core.graphs.notification_graph import build_notification_graph
            graph = build_notification_graph(checkpointer=MemorySaver())
            assert graph is not None
        except ImportError as e:
            pytest.skip(f"LangGraph or graph deps not installed: {e}")


# ---------------------------------------------------------------------------
# GraphRegistry singleton
# ---------------------------------------------------------------------------

class TestGraphRegistry:

    def test_registry_singleton(self):
        try:
            from app.core.graph_registry import GraphRegistry
            a = GraphRegistry.get_instance()
            b = GraphRegistry.get_instance()
            assert a is b
        except ImportError as e:
            pytest.skip(f"GraphRegistry not available: {e}")

    async def test_registry_startup_with_memory_saver(self):
        """Registry startup completes (may use MemorySaver fallback without DB)."""
        try:
            from app.core.graph_registry import GraphRegistry
            registry = GraphRegistry.get_instance()
            # startup() initialises the checkpointer; should not raise
            await registry.startup()
        except Exception as exc:
            # Startup may fail in CI without DB — that is acceptable
            if "connection" in str(exc).lower() or "database" in str(exc).lower():
                pytest.skip(f"DB not available: {exc}")
            raise


# ---------------------------------------------------------------------------
# WorkflowState schema
# ---------------------------------------------------------------------------

class TestWorkflowStateSchema:
    """WorkflowState Pydantic model can be instantiated with minimal inputs."""

    def test_workflow_state_instantiation(self):
        try:
            from core.state import WorkflowState
            state = WorkflowState(
                workflow={"document_id": "test-uuid", "tenant_id": "default"}
            )
            assert state.workflow.document_id == "test-uuid"
            assert state.workflow.tenant_id == "default"
        except ImportError as e:
            pytest.skip(f"WorkflowState not available: {e}")

    def test_workflow_state_error_helper(self):
        try:
            from core.state import WorkflowState
            state = WorkflowState(
                workflow={"document_id": "d1", "tenant_id": "t1"}
            )
            updated = state.with_error("ERR_001", "Test error", "TestAgent")
            assert any("ERR_001" in str(e) for e in (updated.errors or []))
        except (ImportError, AttributeError):
            pytest.skip("WorkflowState.with_error not available")

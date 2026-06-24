"""
GraphRegistry — compile and cache all 6 LangGraph graphs at startup.

Graphs are stateless and thread-safe after compilation.
Each FastAPI/Celery process holds its own compiled graph instances
(LangGraph checkpointer is the shared durable state, not the in-process graph object).
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_registry: Optional["GraphRegistry"] = None


class GraphRegistry:
    """Singleton — call GraphRegistry.get_instance() everywhere."""

    GRAPH_NAMES = (
        "invoice_processing",
        "exception",
        "human_review",
        "approval",
        "retry",
        "notification",
    )

    def __init__(self) -> None:
        self._graphs: Dict[str, Any] = {}
        self._ready = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "GraphRegistry":
        global _registry
        if _registry is None:
            with _lock:
                if _registry is None:
                    _registry = cls()
        return _registry

    def startup(self) -> None:
        """Compile all graphs. Called once during application lifespan startup."""
        try:
            from core.graphs import (
                build_invoice_processing_graph,
                build_exception_graph,
                build_human_review_graph,
                build_approval_graph,
                build_retry_graph,
                build_notification_graph,
            )
            self._graphs = {
                "invoice_processing": build_invoice_processing_graph(),
                "exception": build_exception_graph(),
                "human_review": build_human_review_graph(),
                "approval": build_approval_graph(),
                "retry": build_retry_graph(),
                "notification": build_notification_graph(),
            }
            self._ready = True
            logger.info("GraphRegistry: all 6 graphs compiled and ready")
        except Exception as exc:
            logger.warning(f"GraphRegistry startup failed (non-fatal): {exc}")
            self._ready = False

    def get_graph(self, name: str) -> Any:
        """Return compiled graph by name. Raises KeyError if not ready."""
        if not self._ready:
            raise RuntimeError("GraphRegistry is not initialised — call startup() first")
        if name not in self._graphs:
            raise KeyError(f"Unknown graph '{name}'. Available: {list(self._graphs)}")
        return self._graphs[name]

    def is_ready(self) -> bool:
        return self._ready

    def get_state(self, graph_name: str, thread_id: str) -> Optional[Any]:
        """
        Return the latest state snapshot for a thread from the compiled graph.
        Returns None if the graph is not ready or no checkpoint exists.
        """
        try:
            graph = self.get_graph(graph_name)
            config = {"configurable": {"thread_id": thread_id}}
            snapshot = graph.get_state(config)
            return snapshot
        except Exception:
            return None

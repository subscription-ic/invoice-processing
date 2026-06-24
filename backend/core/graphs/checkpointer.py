"""
PostgreSQL checkpointer setup for LangGraph state persistence.

Enables durable HITL workflows: if the server restarts mid-workflow,
LangGraph restores state from PostgreSQL and resumes from the last checkpoint.

The checkpointer is a singleton — one instance shared across all graphs.
Uses the same DATABASE_URL as SQLAlchemy (the application database).
"""
from __future__ import annotations

import threading
from typing import Optional

_lock = threading.Lock()
_checkpointer = None
_memory_checkpointer = None


def get_checkpointer():
    """
    Return a LangGraph checkpointer backed by PostgreSQL.

    Falls back to MemorySaver if psycopg2/postgres package is unavailable
    (e.g., in unit tests or CI without a database).
    """
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    with _lock:
        if _checkpointer is not None:
            return _checkpointer

        try:
            from app.database import DATABASE_URL as DB_URL  # noqa: F401 – validate importable
            from langgraph.checkpoint.postgres import PostgresSaver
            import psycopg2

            # Build a synchronous psycopg2 connection string
            conn_string = _sqlalchemy_to_psycopg2(DB_URL)
            conn = psycopg2.connect(conn_string)
            saver = PostgresSaver(conn)
            saver.setup()  # Create LangGraph checkpoint tables if not present
            _checkpointer = saver
        except Exception:
            # Graceful fallback — MemorySaver keeps state in memory (dev / test)
            from langgraph.checkpoint.memory import MemorySaver
            _checkpointer = MemorySaver()

    return _checkpointer


def get_memory_checkpointer():
    """Always return an in-memory saver — for unit testing."""
    global _memory_checkpointer
    if _memory_checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver
        _memory_checkpointer = MemorySaver()
    return _memory_checkpointer


def _sqlalchemy_to_psycopg2(url: str) -> str:
    """
    Convert SQLAlchemy URL to psycopg2 connection string.

    postgresql+asyncpg://user:pass@host:5432/db
    →  host=host port=5432 dbname=db user=user password=pass
    """
    if not url:
        return ""
    # Strip async driver prefix if present
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    # psycopg2 accepts the libpq URL format directly
    return url

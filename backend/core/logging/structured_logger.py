"""
StructuredLogger — JSON-structured logging for the platform.

Rules enforced:
- NEVER log PII (names, account numbers, GSTIN, PAN, bank details).
- NEVER log full invoice content — log document_id hash and field names only.
- NEVER log secret values — log the secret key name only.
- All log entries include: timestamp, level, service, tenant_id, document_id (hash).
- Production logs are machine-readable JSON for log aggregation (Azure Monitor, ELK).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# PII field names — values for these keys are always masked before logging
_PII_FIELDS = frozenset(
    {
        "vendor_name",
        "vendor_gstin",
        "gstin",
        "vendor_pan",
        "pan",
        "account_number",
        "bank_account",
        "ifsc_code",
        "swift_code",
        "iban",
        "email",
        "phone",
        "mobile",
        "address",
        "employee_name",
        "employee_code",
        "invoice_number",       # masked to prevent leaking vendor identifiers
        "invoice_content",
        "raw_text",
        "ocr_text",
        "password",
        "secret",
        "token",
        "api_key",
    }
)

_MASK = "***MASKED***"


def _mask_pii(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively mask PII fields in a log data dictionary."""
    masked: Dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in _PII_FIELDS:
            masked[key] = _MASK
        elif isinstance(value, dict):
            masked[key] = _mask_pii(value)
        elif isinstance(value, (list, tuple)):
            masked[key] = [
                _mask_pii(v) if isinstance(v, dict) else v for v in value
            ]
        else:
            masked[key] = value
    return masked


def _hash_id(value: Optional[str]) -> Optional[str]:
    """Convert a sensitive ID to a truncated SHA-256 hash for log correlation."""
    if value is None:
        return None
    return hashlib.sha256(value.encode()).hexdigest()[:12]


class _JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON for machine parsing."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach structured extra fields
        for key, value in vars(record).items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName",
                "exc_info", "exc_text",
            ):
                log_entry[key] = value

        if record.exc_info:
            log_entry["exception"] = traceback.format_exception(*record.exc_info)

        try:
            return json.dumps(log_entry, default=str)
        except Exception:
            return json.dumps({"level": "ERROR", "message": "Log serialisation failed"})


class StructuredLogger:
    """
    Wrapper around the standard library logger that enforces structured
    JSON output and automatic PII masking.

    Usage::

        logger = StructuredLogger("upload_agent")
        logger.info("document_uploaded", document_id_hash="abc123", size_bytes=4096)
        logger.error("upload_failed", error_code="STORAGE_WRITE_ERROR", agent="upload")
    """

    def __init__(
        self,
        name: str,
        environment: str = "development",
        level: str = "INFO",
    ) -> None:
        self._name = name
        self._env = environment
        self._logger = logging.getLogger(f"platform.{name}")
        self._logger.setLevel(getattr(logging, level.upper(), logging.INFO))

        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            if environment == "production":
                handler.setFormatter(_JSONFormatter())
            else:
                handler.setFormatter(
                    logging.Formatter(
                        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
                    )
                )
            self._logger.addHandler(handler)
            self._logger.propagate = False

    # ---------------------------------------------------------------------------
    # Public log methods
    # ---------------------------------------------------------------------------

    def debug(self, event: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._log(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, event, **kwargs)

    def error(self, event: str, exc_info: bool = False, **kwargs: Any) -> None:
        self._log(logging.ERROR, event, exc_info=exc_info, **kwargs)

    def critical(self, event: str, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, event, **kwargs)

    # ---------------------------------------------------------------------------
    # Helpers for common platform log patterns
    # ---------------------------------------------------------------------------

    def agent_start(self, agent: str, document_id: str, tenant_id: str) -> None:
        self.info(
            "agent_start",
            agent=agent,
            document_id_hash=_hash_id(document_id),
            tenant_id=tenant_id,
        )

    def agent_complete(self, agent: str, document_id: str, status: str, duration_ms: float) -> None:
        self.info(
            "agent_complete",
            agent=agent,
            document_id_hash=_hash_id(document_id),
            status=status,
            duration_ms=round(duration_ms, 2),
        )

    def tool_call(self, tool: str, agent: str, duration_ms: float, success: bool) -> None:
        self.debug(
            "tool_call",
            tool=tool,
            agent=agent,
            duration_ms=round(duration_ms, 2),
            success=success,
        )

    def audit_event(self, event: str, document_id: str, agent: str, severity: str = "INFO") -> None:
        self.info(
            "audit_event",
            event=event,
            document_id_hash=_hash_id(document_id),
            agent=agent,
            severity=severity,
        )

    # ---------------------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------------------

    def _log(self, level: int, event: str, exc_info: bool = False, **kwargs: Any) -> None:
        masked = _mask_pii(kwargs)
        masked["event"] = event
        self._logger.log(level, event, extra=masked, exc_info=exc_info)

    def bind(self, **context: Any) -> "BoundLogger":
        """Return a logger with pre-set context fields."""
        return BoundLogger(self, context)


class BoundLogger:
    """Logger with pre-bound context fields, e.g. tenant_id and document_id_hash."""

    def __init__(self, parent: StructuredLogger, context: Dict[str, Any]) -> None:
        self._parent = parent
        self._context = _mask_pii(context)

    def debug(self, event: str, **kwargs: Any) -> None:
        self._parent.debug(event, **{**self._context, **kwargs})

    def info(self, event: str, **kwargs: Any) -> None:
        self._parent.info(event, **{**self._context, **kwargs})

    def warning(self, event: str, **kwargs: Any) -> None:
        self._parent.warning(event, **{**self._context, **kwargs})

    def error(self, event: str, exc_info: bool = False, **kwargs: Any) -> None:
        self._parent.error(event, exc_info=exc_info, **{**self._context, **kwargs})

    def critical(self, event: str, **kwargs: Any) -> None:
        self._parent.critical(event, **{**self._context, **kwargs})


# Module-level convenience
_loggers: Dict[str, StructuredLogger] = {}


def get_logger(name: str, environment: str = "development") -> StructuredLogger:
    """Get or create a named StructuredLogger (singleton per name)."""
    if name not in _loggers:
        _loggers[name] = StructuredLogger(name, environment)
    return _loggers[name]

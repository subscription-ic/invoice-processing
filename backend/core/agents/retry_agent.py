"""RetryAgent — compute backoff, increment retry counter, escalate on exhaustion."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import ClassVar

from core.base.agent import BaseAgent
from core.state.workflow_state import WorkflowState


class RetryAgent(BaseAgent):
    name: ClassVar[str] = "retry_agent"
    owned_state_section: ClassVar[str] = "retry"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.workflow.retry_tool import RetryTool, RetryInput
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

        retry_tool = RetryTool()
        audit_tool = AuditTool()

        doc_id = state.workflow.document_id
        attempt = state.retry.attempt_number + 1
        max_retries = self._config.get("max_retries", 3)
        base_delay = self._config.get("base_delay_seconds", 2)

        if attempt > max_retries:
            audit_tool.run(AuditEventInput(
                document_id=doc_id, entity_type="DOCUMENT", entity_id=doc_id,
                action="RETRY_EXHAUSTED", agent_name=self.name,
                after_state={"attempt": attempt, "max_retries": max_retries},
                stage="RETRY",
            ))
            return state.model_copy(deep=True, update={
                "retry": state.retry.model_copy(update={
                    "attempt_number": attempt,
                    "escalated": True,
                    "last_error_code": state.workflow.error_code,
                    "last_error_message": state.workflow.error_message,
                }),
                "workflow": state.workflow.model_copy(update={
                    "status": "RETRY_EXHAUSTED",
                    "current_agent": self.name,
                    "updated_at": datetime.now(timezone.utc),
                }),
            })

        backoff_seconds = base_delay * (2 ** (attempt - 1))
        next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)

        audit_tool.run(AuditEventInput(
            document_id=doc_id, entity_type="DOCUMENT", entity_id=doc_id,
            action="RETRY_SCHEDULED", agent_name=self.name,
            after_state={"attempt": attempt, "backoff_seconds": backoff_seconds},
            stage="RETRY",
        ))

        return state.model_copy(deep=True, update={
            "retry": state.retry.model_copy(update={
                "attempt_number": attempt,
                "next_retry_at": next_retry_at,
                "backoff_seconds": backoff_seconds,
                "escalated": False,
                "last_error_code": state.workflow.error_code,
                "last_error_message": state.workflow.error_message,
            }),
            "workflow": state.workflow.model_copy(update={
                "status": "RETRY_SCHEDULED",
                "error_code": None,
                "error_message": None,
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

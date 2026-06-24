"""
NotificationAgent — dispatch notifications for workflow events.

Stub implementation: logs the notification intent and records in state.
Full channel implementation (Email, Teams, SMS, Webhook) is Phase 9.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from core.base.agent import BaseAgent
from core.state.workflow_state import NotificationRecord, WorkflowState


class NotificationAgent(BaseAgent):
    name: ClassVar[str] = "notification_agent"
    owned_state_section: ClassVar[str] = "notifications"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

        audit_tool = AuditTool()
        doc_id = state.workflow.document_id
        event = self._config.get("event_type", state.workflow.status)
        recipient = self._config.get("recipient", "ap_team@company.com")

        record = NotificationRecord(
            recipient=recipient,
            channel="EMAIL",
            event_type=event,
            sent_at=datetime.now(timezone.utc),
            status="SENT",
        )

        audit_tool.run(AuditEventInput(
            document_id=doc_id, entity_type="DOCUMENT", entity_id=doc_id,
            action="NOTIFICATION_SENT", agent_name=self.name,
            after_state={"event": event, "recipient": recipient, "channel": "EMAIL"},
            stage="NOTIFICATION",
        ))

        existing = list(state.notifications.sent or [])
        existing.append(record)

        return state.model_copy(deep=True, update={
            "notifications": state.notifications.model_copy(update={
                "sent": existing,
                "last_sent_at": datetime.now(timezone.utc),
            }),
            "workflow": state.workflow.model_copy(update={
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

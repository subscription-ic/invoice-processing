from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.agents.base import AgentState, BaseAgent
from app.core.config import settings
from app.models.models import (
    Document, DocumentStatus, Exception as Ex, ExceptionQueue,
    ExceptionStatus, Notification, ProcessingStage, User, UserRole
)
from app.tools.audit_tool import log_audit, update_workflow_stage


SLA_BY_QUEUE = {
    ExceptionQueue.AP_TEAM: settings.SLA_AP_TEAM_HOURS,
    ExceptionQueue.FINANCE: settings.SLA_FINANCE_HOURS,
    ExceptionQueue.PROCUREMENT: settings.SLA_PROCUREMENT_HOURS,
    ExceptionQueue.COMPLIANCE: settings.SLA_COMPLIANCE_HOURS,
    ExceptionQueue.WAREHOUSE: settings.SLA_WAREHOUSE_HOURS,
}


class ExceptionAgent(BaseAgent):
    """
    Agent 9: EXCEPTION MANAGEMENT
    Creates queues, sets SLAs, assigns to teams, sends notifications.
    """

    name = "EXCEPTION_AGENT"
    progress_on_entry = 20
    progress_on_exit = 25

    def _execute(self, state: AgentState) -> AgentState:
        document_id: str = state["document_id"]
        doc = self.db.query(Document).filter(Document.id == document_id).first()

        # Get all open exceptions for this document
        exceptions = (
            self.db.query(Ex)
            .filter(Ex.document_id == document_id, Ex.status == ExceptionStatus.OPEN)
            .all()
        )

        now = datetime.now(timezone.utc)

        for ex in exceptions:
            # Set SLA deadline
            sla_hours = SLA_BY_QUEUE.get(ex.queue, settings.SLA_AP_TEAM_HOURS)
            ex.sla_hours = sla_hours
            ex.sla_deadline = now + timedelta(hours=sla_hours)
            ex.status = ExceptionStatus.OPEN

            # Auto-assign to first available team member
            team_member = self._find_assignee(ex.queue)
            if team_member:
                ex.assigned_to = team_member.id

            # Send notification
            self._notify_team(ex, doc)

            log_audit(
                self.db,
                document_id=document_id,
                entity_type="EXCEPTION",
                entity_id=str(ex.id),
                action="EXCEPTION_CREATED",
                agent=self.name,
                after_state={
                    "exception_type": ex.exception_type,
                    "queue": ex.queue,
                    "severity": ex.severity,
                    "sla_deadline": ex.sla_deadline.isoformat() if ex.sla_deadline else None,
                    "assigned_to": str(ex.assigned_to) if ex.assigned_to else None,
                },
                stage=ProcessingStage.EXCEPTION,
            )

        doc.status = DocumentStatus.HUMAN_REVIEW_REQUIRED
        self.db.flush()

        update_workflow_stage(
            self.db, document_id=document_id,
            stage=ProcessingStage.EXCEPTION,
            agent=self.name, progress_percent=25,
        )

        state.set_status("HUMAN_REVIEW_REQUIRED")
        return state

    def _find_assignee(self, queue: str) -> User | None:
        role_map = {
            ExceptionQueue.AP_TEAM: UserRole.AP_TEAM,
            ExceptionQueue.FINANCE: UserRole.FINANCE,
            ExceptionQueue.PROCUREMENT: UserRole.PROCUREMENT,
            ExceptionQueue.COMPLIANCE: UserRole.ADMIN,
            ExceptionQueue.WAREHOUSE: UserRole.AP_TEAM,
        }
        role = role_map.get(queue)
        if not role:
            return None
        return self.db.query(User).filter(User.role == role, User.is_active == True).first()

    def _notify_team(self, ex: Ex, doc: Document) -> None:
        if not ex.assigned_to:
            return
        notif = Notification(
            user_id=str(ex.assigned_to),
            document_id=ex.document_id,
            notification_type="EXCEPTION_ASSIGNED",
            title=f"Exception: {ex.title}",
            body=f"Document {doc.document_id} requires your attention. SLA: {ex.sla_hours}h. "
                 f"Queue: {ex.queue}. Type: {ex.exception_type}",
            action_url=f"/exceptions/{ex.id}",
        )
        self.db.add(notif)
        self.db.flush()
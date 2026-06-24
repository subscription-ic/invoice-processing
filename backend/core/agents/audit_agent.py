"""AuditAgent — write terminal audit event and mark the workflow as completed."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from core.base.agent import BaseAgent
from core.state.workflow_state import WorkflowState


class AuditAgent(BaseAgent):
    name: ClassVar[str] = "audit_agent"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

        audit_tool = AuditTool()
        doc_id = state.workflow.document_id

        audit_tool.run(AuditEventInput(
            document_id=doc_id,
            entity_type="DOCUMENT",
            entity_id=doc_id,
            action="WORKFLOW_COMPLETED",
            agent_name=self.name,
            after_state={"final_status": state.workflow.status},
            stage="AUDIT",
        ))

        return state.model_copy(deep=True, update={
            "workflow": state.workflow.model_copy(update={
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

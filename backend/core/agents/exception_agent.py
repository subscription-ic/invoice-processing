"""ExceptionAgent — create exception record and assign to the correct review queue."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from core.base.agent import BaseAgent
from core.state.workflow_state import WorkflowState


class ExceptionAgent(BaseAgent):
    name: ClassVar[str] = "exception_agent"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.workflow.exception_tool import ExceptionTool, ExceptionInput
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

        exception_tool = ExceptionTool()
        audit_tool = AuditTool()

        doc_id = state.workflow.document_id
        validation_errors = state.validation.errors or []

        # Determine exception type and queue from validation errors
        has_duplicate = any(e.error_code == "DUPLICATE" for e in validation_errors)
        has_arithmetic = any(e.rule == "ARITHMETIC" for e in validation_errors)
        has_gst = any(e.rule == "GST_FORMAT" for e in validation_errors)
        has_profile = state.exception.exception_type == "PROFILE_VALIDATION_FAILED"

        if has_duplicate:
            exc_type, queue, severity = "DUPLICATE_INVOICE", "AP_TEAM", "CRITICAL"
        elif has_arithmetic:
            exc_type, queue, severity = "ARITHMETIC_ERROR", "FINANCE", "HIGH"
        elif has_gst:
            exc_type, queue, severity = "GST_VALIDATION_ERROR", "COMPLIANCE", "MEDIUM"
        elif has_profile:
            exc_type = "PROFILE_VALIDATION_FAILED"
            queue = state.exception.assigned_queue or "AP_TEAM"
            severity = "HIGH"
        else:
            exc_type = state.exception.exception_type or "GENERAL_EXCEPTION"
            queue = state.exception.assigned_queue or "AP_TEAM"
            severity = "MEDIUM"

        description = "; ".join(e.message for e in validation_errors[:5]) or "Manual review required"

        result = exception_tool.run(ExceptionInput(
            document_id=doc_id,
            exception_type=exc_type,
            severity=severity,
            queue=queue,
            description=description,
            agent_name=self.name,
        ))

        audit_tool.run(AuditEventInput(
            document_id=doc_id,
            entity_type="DOCUMENT",
            entity_id=doc_id,
            action="EXCEPTION_CREATED",
            agent_name=self.name,
            after_state={"exception_id": result.exception_id, "queue": queue, "severity": severity},
            stage="EXCEPTION",
        ))

        return state.model_copy(deep=True, update={
            "exception": state.exception.model_copy(update={
                "exception_id": result.exception_id,
                "exception_type": exc_type,
                "assigned_queue": queue,
                "severity": severity,
                "sla_deadline": result.sla_deadline,
                "resolution_status": "OPEN",
            }),
            "routing": state.routing.model_copy(update={"requires_human_review": True}),
            "workflow": state.workflow.model_copy(update={
                "status": "EXCEPTION",
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

"""ProfileValidationAgent — enforce business-profile-specific mandatory field rules."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, Optional

from core.base.agent import BaseAgent
from core.state.workflow_state import ValidationError, WorkflowState


class ProfileValidationAgent(BaseAgent):
    name: ClassVar[str] = "profile_validation_agent"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.validation.profile_validation_tool import (
            ProfileValidationTool,
            ProfileValidationInput,
        )
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput
        from app.tools.workflow.exception_tool import ExceptionTool, ExceptionInput

        profile_tool = ProfileValidationTool()
        audit_tool = AuditTool()

        inv = state.invoice
        doc_id = state.workflow.document_id
        profile = state.profile.business_profile or "NON_PO_OPEX"

        result = profile_tool.run(ProfileValidationInput(
            business_profile=profile,
            invoice_number=inv.invoice_number,
            vendor_name=inv.vendor_name,
            vendor_gstin=inv.vendor_gstin,
            total_amount=float(inv.total_amount) if inv.total_amount else None,
            invoice_date=str(inv.invoice_date) if inv.invoice_date else None,
            po_number=inv.po_number,
            grn_number=inv.grn_number,
            document_id=doc_id,
        ))

        audit_tool.run(AuditEventInput(
            document_id=doc_id,
            entity_type="DOCUMENT",
            entity_id=doc_id,
            action="PROFILE_VALIDATION_COMPLETED",
            agent_name=self.name,
            after_state={"valid": result.is_valid, "missing_fields": result.missing_fields},
            stage="BUSINESS_PROFILE",
        ))

        errors = [
            ValidationError(
                field=f,
                rule="MANDATORY_FIELD_MISSING",
                message=f"Mandatory field '{f}' is missing for profile {profile}",
                severity="ERROR",
            )
            for f in (result.missing_fields or [])
        ]

        new_profile_validation = state.profile_validation.model_copy(update={
            "is_valid": result.is_valid,
            "errors": errors,
        })

        if not result.is_valid:
            exception_tool = ExceptionTool()
            ex = exception_tool.run(ExceptionInput(
                document_id=doc_id,
                exception_type="PROFILE_VALIDATION_FAILED",
                severity="HIGH",
                queue="AP_TEAM",
                description=f"Missing fields for {profile}: {', '.join(result.missing_fields or [])}",
                agent_name=self.name,
            ))
            return state.model_copy(deep=True, update={
                "profile_validation": new_profile_validation,
                "exception": state.exception.model_copy(update={
                    "exception_id": ex.exception_id,
                    "exception_type": "PROFILE_VALIDATION_FAILED",
                    "assigned_queue": "AP_TEAM",
                    "severity": "HIGH",
                }),
                "routing": state.routing.model_copy(update={"requires_human_review": True}),
                "workflow": state.workflow.model_copy(update={
                    "status": "EXCEPTION",
                    "current_agent": self.name,
                    "updated_at": datetime.now(timezone.utc),
                }),
            })

        return state.model_copy(deep=True, update={
            "profile_validation": new_profile_validation,
            "workflow": state.workflow.model_copy(update={
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

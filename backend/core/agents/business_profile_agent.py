"""
BusinessProfileAgent — confirm or refine business profile using AI + rules.

Node ID: `profile` in InvoiceProcessingGraph.
ClassificationAgent does initial profile detection; this agent refines it
using full InvoiceData (not available to ClassificationAgent at that point).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from core.base.agent import BaseAgent
from core.state.workflow_state import WorkflowState

VALID_PROFILES = frozenset({
    "PO_RAW_MATERIAL", "NON_PO_RAW_MATERIAL",
    "PO_CAPEX", "NON_PO_CAPEX",
    "PO_OPEX", "NON_PO_OPEX",
    "LEASE_RENT", "EMPLOYEE_REIMBURSEMENT", "PETTY_CASH",
})


class BusinessProfileAgent(BaseAgent):
    name: ClassVar[str] = "business_profile_agent"
    owned_state_section: ClassVar[str] = "profile"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.ai.classification_tool import ClassificationTool, ClassificationInput
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

        audit_tool = AuditTool()
        classification_tool = ClassificationTool()

        doc_id = state.workflow.document_id
        inv = state.invoice
        raw_text = state.ocr.raw_text or ""

        # If profile already set with high confidence, skip re-classification
        if state.profile.business_profile in VALID_PROFILES and (state.profile.profile_confidence or 0) >= 0.80:
            audit_tool.run(AuditEventInput(
                document_id=doc_id, entity_type="DOCUMENT", entity_id=doc_id,
                action="PROFILE_CONFIRMED", agent_name=self.name,
                after_state={"business_profile": state.profile.business_profile, "source": "carry_forward"},
                stage="BUSINESS_PROFILE",
            ))
            return state.model_copy(deep=True, update={
                "workflow": state.workflow.model_copy(update={
                    "status": "PROFILED",
                    "current_agent": self.name,
                    "updated_at": datetime.now(timezone.utc),
                }),
            })

        # Re-classify with full invoice data now available
        full_text = "\n".join(filter(None, [
            raw_text,
            f"Invoice Number: {inv.invoice_number}",
            f"Vendor: {inv.vendor_name}",
            f"PO Number: {inv.po_number}",
            f"GRN Number: {inv.grn_number}",
            f"Amount: {inv.total_amount} {inv.currency}",
        ]))

        result = classification_tool.run(ClassificationInput(
            raw_text=full_text,
            document_id=doc_id,
            filename=state.document.original_filename,
        ))

        business_profile = result.business_profile
        if business_profile not in VALID_PROFILES:
            business_profile = state.profile.business_profile or "NON_PO_OPEX"

        # Apply deterministic override rules
        method = "AI"
        if inv.po_number and business_profile.startswith("NON_PO_"):
            # Invoice explicitly has a PO number but AI said NON_PO
            business_profile = business_profile.replace("NON_PO_", "PO_")
            method = "HYBRID"
        elif not inv.po_number and business_profile.startswith("PO_") and result.confidence < 0.75:
            business_profile = business_profile.replace("PO_", "NON_PO_")
            method = "HYBRID"

        audit_tool.run(AuditEventInput(
            document_id=doc_id, entity_type="DOCUMENT", entity_id=doc_id,
            action="PROFILE_ASSIGNED", agent_name=self.name,
            after_state={"business_profile": business_profile, "confidence": result.confidence, "method": method},
            stage="BUSINESS_PROFILE",
        ))

        return state.model_copy(deep=True, update={
            "profile": state.profile.model_copy(update={
                "business_profile": business_profile,
                "profile_confidence": result.confidence,
                "profile_reasoning": result.reasoning,
                "classification_method": method,
            }),
            "workflow": state.workflow.model_copy(update={
                "status": "PROFILED",
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

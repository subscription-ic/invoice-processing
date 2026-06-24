"""
MatchingAgent — vendor, PO, GRN, and 3-way matching.

Populates state.matching nested POMatchResult / GRNMatchResult / ThreeWayMatchResult.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, Optional

from core.base.agent import BaseAgent
from core.state.workflow_state import (
    GRNMatchResult,
    MatchingInfo,
    POMatchResult,
    ThreeWayMatchResult,
    WorkflowState,
)


class MatchingAgent(BaseAgent):
    name: ClassVar[str] = "matching_agent"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.matching.vendor_matching_tool import VendorMatchingTool, VendorMatchInput
        from app.tools.matching.po_matching_tool import POMatchingTool, POMatchInput
        from app.tools.matching.grn_matching_tool import GRNMatchingTool, GRNMatchInput
        from app.tools.matching.three_way_matching_tool import ThreeWayMatchingTool, ThreeWayMatchInput
        from app.tools.erp.gl_code_tool import GLCodeTool, GLCodeInput
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

        vendor_tool = VendorMatchingTool()
        po_tool = POMatchingTool()
        grn_tool = GRNMatchingTool()
        three_way_tool = ThreeWayMatchingTool()
        gl_tool = GLCodeTool()
        audit_tool = AuditTool()

        inv = state.invoice
        doc_id = state.workflow.document_id
        tenant_id = state.workflow.tenant_id
        profile = state.profile.business_profile or "NON_PO_OPEX"

        # Vendor match
        vendor_match = vendor_tool.run(VendorMatchInput(
            extracted_vendor_name=inv.vendor_name,
            extracted_gstin=inv.vendor_gstin,
            document_id=doc_id,
            tenant_id=tenant_id,
        ))
        vendor_id = vendor_match.vendor_id

        # PO match
        po_result = None
        if inv.po_number or vendor_id:
            po_result = po_tool.run(POMatchInput(
                po_number=inv.po_number,
                vendor_id=vendor_id,
                invoice_total=float(inv.total_amount or 0),
                document_id=doc_id,
                tenant_id=tenant_id,
            ))

        # GRN match
        grn_result = None
        if inv.grn_number or (po_result and po_result.matched):
            grn_result = grn_tool.run(GRNMatchInput(
                grn_number=inv.grn_number,
                po_id=po_result.po_id if (po_result and po_result.matched) else None,
                document_id=doc_id,
                tenant_id=tenant_id,
            ))

        # 3-way match
        three_way = three_way_tool.run(ThreeWayMatchInput(
            document_id=doc_id,
            po_id=po_result.po_id if po_result else None,
            grn_id=grn_result.grn_id if grn_result else None,
            invoice_total=float(inv.total_amount or 0),
            po_match_score=po_result.match_score if po_result else 0.0,
            grn_match_score=grn_result.match_score if grn_result else 0.0,
            vendor_match_score=vendor_match.match_score,
            tenant_id=tenant_id,
        ))

        # GL codes for this profile
        gl = gl_tool.run(GLCodeInput(business_profile=profile, tenant_id=tenant_id))

        audit_tool.run(AuditEventInput(
            document_id=doc_id,
            entity_type="DOCUMENT",
            entity_id=doc_id,
            action="MATCHING_COMPLETED",
            agent_name=self.name,
            after_state={
                "vendor_matched": vendor_match.matched,
                "po_matched": po_result.matched if po_result else False,
                "disposition": three_way.match_status,
                "overall_score": three_way.overall_score,
            },
            stage="PO_GRN_MATCHING",
        ))

        new_po = POMatchResult(
            status="MATCHED" if (po_result and po_result.matched) else "NOT_FOUND",
            match_score=po_result.match_score if po_result else 0.0,
            po_id=po_result.po_id if po_result else None,
            po_number=po_result.po_number if po_result else None,
        )

        new_grn = GRNMatchResult(
            status="MATCHED" if (grn_result and grn_result.matched) else "NOT_FOUND",
            match_score=grn_result.match_score if grn_result else 0.0,
            grn_id=grn_result.grn_id if grn_result else None,
            grn_number=grn_result.grn_number if grn_result else None,
        )

        # Map tool match_status → WorkflowState disposition values
        disposition_map = {
            "FULL_MATCH": "FULL_MATCH",
            "PARTIAL_MATCH": "PARTIAL_MATCH",
            "NO_MATCH": "FAILED_MATCH",
        }
        disposition = disposition_map.get(three_way.match_status, "FAILED_MATCH")

        new_three_way = ThreeWayMatchResult(
            disposition=disposition,
            overall_score=three_way.overall_score,
            exception_required=three_way.match_status == "NO_MATCH",
            approval_required=three_way.match_status in ("PARTIAL_MATCH", "NO_MATCH"),
            match_summary=three_way.routing_recommendation,
        )

        # Store GL codes on invoice for ERP posting
        new_invoice = inv.model_copy(update={
            "gl_code": gl.expense_gl,
        })

        return state.model_copy(deep=True, update={
            "matching": MatchingInfo(po_match=new_po, grn_match=new_grn, three_way=new_three_way),
            "invoice": new_invoice,
            "workflow": state.workflow.model_copy(update={
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

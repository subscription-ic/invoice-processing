"""ExtractionAgent — extract structured invoice data from OCR text using GPT-4o."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, Optional

from core.base.agent import BaseAgent
from core.state.workflow_state import WorkflowState


class ExtractionAgent(BaseAgent):
    name: ClassVar[str] = "extraction_agent"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.ai.extraction_tool import ExtractionTool, ExtractionInput
        from app.tools.ai.normalization_tool import NormalizationTool, NormalizationInput
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

        extraction_tool = ExtractionTool()
        normalization_tool = NormalizationTool()
        audit_tool = AuditTool()

        doc_id = state.workflow.document_id
        ocr_text = state.ocr.raw_text or ""
        business_profile = state.profile.business_profile

        if not ocr_text:
            return state.with_error("NO_TEXT", "No text available for extraction", self.name)

        extract_result = extraction_tool.run(ExtractionInput(
            raw_text=ocr_text,
            document_id=doc_id,
            business_profile=business_profile,
        ))

        if not extract_result.success:
            return state.with_error(
                extract_result.error_code or "EXTRACTION_FAILED",
                extract_result.error_message or "Extraction failed",
                self.name,
            )

        norm_result = normalization_tool.run(NormalizationInput(
            invoice_number=extract_result.invoice_number,
            invoice_date=extract_result.invoice_date,
            due_date=extract_result.due_date,
            total_amount=str(extract_result.total_amount) if extract_result.total_amount else None,
            tax_amount=str(extract_result.tax_amount) if extract_result.tax_amount else None,
            vendor_gstin=extract_result.vendor_gstin,
            currency=extract_result.currency,
            payment_terms=extract_result.payment_terms,
        ))

        from core.state.workflow_state import LineItem as WFLineItem
        from decimal import Decimal
        line_items = [
            WFLineItem(
                description=li.description,
                quantity=Decimal(str(li.quantity)) if li.quantity else None,
                unit_price=Decimal(str(li.unit_price)) if li.unit_price else None,
                total=Decimal(str(li.total)) if li.total else None,
                hsn_sac=li.hsn_sac,
                tax_rate=li.gst_rate,
            )
            for li in (extract_result.line_items or [])
        ]

        new_invoice = state.invoice.model_copy(update={
            "invoice_number": norm_result.invoice_number,
            "invoice_date": norm_result.invoice_date,
            "due_date": norm_result.due_date,
            "vendor_name": extract_result.vendor_name,
            "vendor_gstin": norm_result.vendor_gstin,
            "vendor_address": extract_result.vendor_address,
            "buyer_name": extract_result.buyer_name,
            "buyer_gstin": extract_result.buyer_gstin,
            "po_number": extract_result.po_number,
            "grn_number": extract_result.grn_number,
            "tax_amount": Decimal(str(norm_result.tax_amount)) if norm_result.tax_amount else None,
            "total_amount": Decimal(str(norm_result.total_amount)) if norm_result.total_amount else None,
            "currency": norm_result.currency or "INR",
            "payment_terms": norm_result.payment_terms,
            "line_items": line_items,
        })

        new_extraction = state.extraction.model_copy(update={
            "field_confidences": extract_result.field_confidences,
            "llm_model": extract_result.model_used,
            "token_count": extract_result.tokens_used,
        })

        audit_tool.run(AuditEventInput(
            document_id=doc_id,
            entity_type="DOCUMENT",
            entity_id=doc_id,
            action="DATA_EXTRACTED",
            agent_name=self.name,
            after_state={
                "invoice_number": norm_result.invoice_number,
                "vendor_name": extract_result.vendor_name,
                "total_amount": norm_result.total_amount,
            },
            stage="EXTRACTION",
        ))

        return state.model_copy(deep=True, update={
            "invoice": new_invoice,
            "extraction": new_extraction,
            "workflow": state.workflow.model_copy(update={
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

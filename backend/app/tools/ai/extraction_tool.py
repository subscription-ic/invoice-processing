"""
ExtractionTool — extract structured invoice data from OCR text using GPT-4o.

This is the core LLM extraction tool. It uses the prompt YAML files
from app/prompts/ and returns a strongly-typed InvoiceData object.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

import yaml
from pydantic import Field

from core.base.tool import BaseTool, ToolInput, ToolOutput

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


class ExtractionInput(ToolInput):
    raw_text: str
    document_id: str
    page_images: Optional[List[bytes]] = None
    business_profile: Optional[str] = None
    tenant_id: str = "default"
    model: Optional[str] = None


class ExtractedLineItem(ToolInput):
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    total: Optional[float] = None
    hsn_sac: Optional[str] = None
    gst_rate: Optional[float] = None
    discount: Optional[float] = None


class ExtractionOutput(ToolOutput):
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    vendor_address: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_gstin: Optional[str] = None
    po_number: Optional[str] = None
    grn_number: Optional[str] = None
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    total_amount: Optional[float] = None
    currency: str = "INR"
    payment_terms: Optional[str] = None
    bank_account: Optional[str] = None
    ifsc_code: Optional[str] = None
    line_items: List[ExtractedLineItem] = Field(default_factory=list)
    raw_extracted: Dict[str, Any] = Field(default_factory=dict)
    field_confidences: Dict[str, float] = Field(default_factory=dict)
    overall_confidence: float = 0.0
    model_used: Optional[str] = None
    tokens_used: int = 0
    error_code: Optional[str] = None


class ExtractionTool(BaseTool[ExtractionInput, ExtractionOutput]):
    name: ClassVar[str] = "extraction"
    description: ClassVar[str] = "Extract structured invoice fields from OCR text using GPT-4o"
    input_model: ClassVar = ExtractionInput
    output_model: ClassVar = ExtractionOutput

    def __init__(self, llm_provider=None, **kwargs):
        super().__init__(**kwargs)
        self._llm = llm_provider

    def _get_llm(self):
        if self._llm is None:
            from core.container import get_container
            self._llm = get_container().llm_provider
        return self._llm

    def _execute(self, input_data: ExtractionInput) -> ExtractionOutput:
        import asyncio
        from core.providers.llm_provider import LLMMessage

        try:
            system_prompt, user_prompt = self._build_prompts(input_data)
            llm = self._get_llm()
            messages = [
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_prompt),
            ]
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(llm.complete(
                messages=messages,
                model=input_data.model,
                temperature=0.0,
                max_tokens=4096,
                json_mode=True,
            ))
            data = json.loads(response.content)
            return self._map_to_output(data, response.model, response.input_tokens + response.output_tokens)
        except Exception as exc:
            return ExtractionOutput(
                success=False,
                error_code="EXTRACTION_FAILED",
                error_message=str(exc),
            )

    def _build_prompts(self, input_data: ExtractionInput):
        try:
            prompt_file = PROMPTS_DIR / "extraction_agent.yaml"
            if prompt_file.exists():
                with open(prompt_file) as f:
                    prompt_config = yaml.safe_load(f)
                system_prompt = prompt_config.get("system_prompt", self._default_system())
            else:
                system_prompt = self._default_system()
        except Exception:
            system_prompt = self._default_system()

        user_prompt = f"""Extract all invoice fields from the following document text.
Business Profile: {input_data.business_profile or 'UNKNOWN'}
Document ID: {input_data.document_id}

--- DOCUMENT TEXT ---
{input_data.raw_text[:6000]}
--- END ---

Return a JSON object with all extractable invoice fields."""

        return system_prompt, user_prompt

    def _default_system(self):
        return """You are an expert invoice data extraction system. Extract structured data from invoice text.

Return a JSON object with these fields (use null for missing fields):
{
  "invoice_number": string,
  "invoice_date": "YYYY-MM-DD",
  "due_date": "YYYY-MM-DD",
  "vendor_name": string,
  "vendor_gstin": string,
  "vendor_address": string,
  "buyer_name": string,
  "buyer_gstin": string,
  "po_number": string,
  "grn_number": string,
  "subtotal": number,
  "tax_amount": number,
  "total_amount": number,
  "currency": "INR",
  "payment_terms": string,
  "bank_account": string,
  "ifsc_code": string,
  "line_items": [{"description": string, "quantity": number, "unit_price": number, "total": number, "hsn_sac": string, "gst_rate": number}],
  "field_confidences": {"invoice_number": 0.9, ...},
  "overall_confidence": 0.85
}"""

    def _map_to_output(self, data: dict, model: str, tokens: int) -> ExtractionOutput:
        line_items = []
        for li in data.get("line_items", []):
            if isinstance(li, dict):
                line_items.append(ExtractedLineItem(
                    description=li.get("description"),
                    quantity=li.get("quantity"),
                    unit_price=li.get("unit_price"),
                    total=li.get("total"),
                    hsn_sac=li.get("hsn_sac"),
                    gst_rate=li.get("gst_rate"),
                    discount=li.get("discount"),
                ))

        return ExtractionOutput(
            success=True,
            invoice_number=data.get("invoice_number"),
            invoice_date=data.get("invoice_date"),
            due_date=data.get("due_date"),
            vendor_name=data.get("vendor_name"),
            vendor_gstin=data.get("vendor_gstin"),
            vendor_address=data.get("vendor_address"),
            buyer_name=data.get("buyer_name"),
            buyer_gstin=data.get("buyer_gstin"),
            po_number=data.get("po_number"),
            grn_number=data.get("grn_number"),
            subtotal=data.get("subtotal"),
            tax_amount=data.get("tax_amount"),
            total_amount=data.get("total_amount"),
            currency=data.get("currency", "INR"),
            payment_terms=data.get("payment_terms"),
            bank_account=data.get("bank_account"),
            ifsc_code=data.get("ifsc_code"),
            line_items=line_items,
            raw_extracted=data,
            field_confidences=data.get("field_confidences", {}),
            overall_confidence=data.get("overall_confidence", 0.7),
            model_used=model,
            tokens_used=tokens,
        )

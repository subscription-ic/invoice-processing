"""ClassificationTool — classify document type and business profile via GPT-4o."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

import yaml

from core.base.tool import BaseTool, ToolInput, ToolOutput

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

VALID_PROFILES = {
    "PO_RAW_MATERIAL", "NON_PO_RAW_MATERIAL",
    "PO_CAPEX", "NON_PO_CAPEX",
    "PO_OPEX", "NON_PO_OPEX",
    "LEASE_RENT", "EMPLOYEE_REIMBURSEMENT", "PETTY_CASH",
}


class ClassificationInput(ToolInput):
    raw_text: str
    document_id: str
    page_image: Optional[bytes] = None
    filename: Optional[str] = None
    declared_type: Optional[str] = None
    model: Optional[str] = None


class ClassificationOutput(ToolOutput):
    doc_type: Optional[str] = None
    business_profile: Optional[str] = None
    confidence: float = 0.0
    reasoning: Optional[str] = None
    is_invoice: bool = False
    has_po_reference: bool = False
    model_used: Optional[str] = None
    error_code: Optional[str] = None


class ClassificationTool(BaseTool[ClassificationInput, ClassificationOutput]):
    name: ClassVar[str] = "classification"
    description: ClassVar[str] = "Classify document type and AP business profile using GPT-4o"
    input_model: ClassVar = ClassificationInput
    output_model: ClassVar = ClassificationOutput

    def __init__(self, llm_provider=None, **kwargs):
        super().__init__(**kwargs)
        self._llm = llm_provider

    def _get_llm(self):
        if self._llm is None:
            from core.container import get_container
            self._llm = get_container().llm_provider
        return self._llm

    def _execute(self, input_data: ClassificationInput) -> ClassificationOutput:
        from core.providers.llm_provider import LLMMessage

        try:
            system_prompt = self._load_prompt()
            user_prompt = f"""Classify this document.
Document text (first 2000 chars):
{input_data.raw_text[:2000]}

Filename: {input_data.filename or 'unknown'}
Declared type: {input_data.declared_type or 'not specified'}

Return JSON: {{
  "doc_type": "INVOICE|CREDIT_NOTE|DEBIT_NOTE|RECEIPT|OTHER",
  "business_profile": one of {sorted(VALID_PROFILES)},
  "confidence": 0.0-1.0,
  "is_invoice": true|false,
  "has_po_reference": true|false,
  "reasoning": "one sentence"
}}"""
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
                max_tokens=512,
                json_mode=True,
            ))
            data = json.loads(response.content)
            profile = data.get("business_profile", "NON_PO_OPEX")
            if profile not in VALID_PROFILES:
                profile = "NON_PO_OPEX"
            return ClassificationOutput(
                success=True,
                doc_type=data.get("doc_type", "INVOICE"),
                business_profile=profile,
                confidence=float(data.get("confidence", 0.7)),
                reasoning=data.get("reasoning"),
                is_invoice=bool(data.get("is_invoice", True)),
                has_po_reference=bool(data.get("has_po_reference", False)),
                model_used=response.model,
            )
        except Exception as exc:
            return ClassificationOutput(
                success=False,
                error_code="CLASSIFICATION_FAILED",
                error_message=str(exc),
            )

    def _load_prompt(self) -> str:
        prompt_file = PROMPTS_DIR / "classification_agent.yaml"
        if prompt_file.exists():
            try:
                with open(prompt_file) as f:
                    cfg = yaml.safe_load(f)
                return cfg.get("system_prompt", self._default_system())
            except Exception:
                pass
        return self._default_system()

    def _default_system(self) -> str:
        return (
            "You are an expert AP document classifier. Classify documents into their invoice type "
            "and business profile for an Indian enterprise accounts payable system. "
            "Always return valid JSON."
        )

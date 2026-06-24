"""LLMTool — stateless wrapper over the injected LLMProviderInterface."""
from __future__ import annotations

import asyncio
import json
from typing import Any, ClassVar, Dict, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class LLMCompletionInput(ToolInput):
    system_prompt: str
    user_prompt: str
    model: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 4096
    json_mode: bool = True
    document_id: Optional[str] = None


class LLMCompletionOutput(ToolOutput):
    content: Optional[str] = None
    parsed: Optional[Dict[str, Any]] = None
    model_used: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    error_code: Optional[str] = None


class LLMTool(BaseTool[LLMCompletionInput, LLMCompletionOutput]):
    name: ClassVar[str] = "llm"
    description: ClassVar[str] = "Text completion via the configured LLM provider"
    input_model: ClassVar = LLMCompletionInput
    output_model: ClassVar = LLMCompletionOutput

    def __init__(self, llm_provider=None, **kwargs):
        super().__init__(**kwargs)
        self._llm = llm_provider

    def _get_llm(self):
        if self._llm is None:
            from core.container import get_container
            self._llm = get_container().llm_provider
        return self._llm

    def _execute(self, input_data: LLMCompletionInput) -> LLMCompletionOutput:
        try:
            from core.providers.llm_provider import LLMMessage
            llm = self._get_llm()
            messages = [
                LLMMessage(role="system", content=input_data.system_prompt),
                LLMMessage(role="user", content=input_data.user_prompt),
            ]
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(llm.complete(
                messages=messages,
                model=input_data.model,
                temperature=input_data.temperature,
                max_tokens=input_data.max_tokens,
                json_mode=input_data.json_mode,
            ))
            parsed = None
            if input_data.json_mode:
                try:
                    parsed = json.loads(response.content)
                except Exception:
                    pass
            return LLMCompletionOutput(
                success=True,
                content=response.content,
                parsed=parsed,
                model_used=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
        except Exception as exc:
            return LLMCompletionOutput(
                success=False,
                error_code="LLM_FAILED",
                error_message=str(exc),
            )


class VisionLLMInput(ToolInput):
    system_prompt: str
    user_prompt: str
    image_bytes: bytes
    model: Optional[str] = None
    json_mode: bool = True
    max_tokens: int = 4096
    document_id: Optional[str] = None


class VisionLLMOutput(ToolOutput):
    content: Optional[str] = None
    parsed: Optional[Dict[str, Any]] = None
    model_used: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    error_code: Optional[str] = None


class VisionLLMTool(BaseTool[VisionLLMInput, VisionLLMOutput]):
    name: ClassVar[str] = "vision_llm"
    description: ClassVar[str] = "Vision + text completion for image-based extraction"
    input_model: ClassVar = VisionLLMInput
    output_model: ClassVar = VisionLLMOutput

    def __init__(self, llm_provider=None, **kwargs):
        super().__init__(**kwargs)
        self._llm = llm_provider

    def _get_llm(self):
        if self._llm is None:
            from core.container import get_container
            self._llm = get_container().llm_provider
        return self._llm

    def _execute(self, input_data: VisionLLMInput) -> VisionLLMOutput:
        try:
            llm = self._get_llm()
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(llm.complete_with_vision(
                system_prompt=input_data.system_prompt,
                user_prompt=input_data.user_prompt,
                image_bytes=input_data.image_bytes,
                model=input_data.model,
                json_mode=input_data.json_mode,
                max_tokens=input_data.max_tokens,
            ))
            parsed = None
            if input_data.json_mode:
                try:
                    parsed = json.loads(response.content)
                except Exception:
                    pass
            return VisionLLMOutput(
                success=True,
                content=response.content,
                parsed=parsed,
                model_used=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
        except Exception as exc:
            return VisionLLMOutput(
                success=False,
                error_code="VISION_LLM_FAILED",
                error_message=str(exc),
            )

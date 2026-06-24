"""
LLMProvider — interface and OpenAI implementation.

All LLM calls in the platform go through this interface.
Supports JSON-mode, vision (image+text), and plain text completions.
Prompt versioning and Jinja2 rendering happen in the PromptRegistry (Phase 9);
this provider is transport only.
"""

from __future__ import annotations

import base64
import json
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional, Union

from core.base.provider import BaseProvider


@dataclass
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: Union[str, List[Dict[str, Any]]]


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = "stop"
    raw: Optional[Dict[str, Any]] = None

    def as_json(self) -> Dict[str, Any]:
        """Parse content as JSON. Raises ValueError if not valid JSON."""
        try:
            return json.loads(self.content)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"LLM response is not valid JSON: {self.content[:200]}"
            ) from exc


class LLMProviderInterface(BaseProvider):
    """
    Abstract LLM provider. Implementations: OpenAILLMProvider (active),
    AzureOpenAILLMProvider (Phase 9 migration), AnthropicLLMProvider (stub).
    """

    provider_type: ClassVar[str] = "llm"

    @abstractmethod
    async def complete(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Standard text completion."""

    @abstractmethod
    async def complete_with_vision(
        self,
        system_prompt: str,
        user_prompt: str,
        image_bytes: bytes,
        model: Optional[str] = None,
        json_mode: bool = True,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Vision completion — sends an image alongside the text prompt."""


class OpenAILLMProvider(LLMProviderInterface):
    """
    OpenAI chat completion provider.

    Wraps the OpenAI Python SDK (v1+). Uses gpt-4o by default.
    Client is created lazily to avoid import-time API key validation.
    """

    provider_name: ClassVar[str] = "openai"

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "gpt-4o",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._timeout = timeout
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            from app.core.config import settings

            key = self._api_key or settings.OPENAI_API_KEY
            if not key:
                from core.base.exceptions import ConfigurationException
                raise ConfigurationException(
                    "OPENAI_API_KEY is not configured",
                    config_key="openai.api_key",
                )
            self._client = AsyncOpenAI(api_key=key, timeout=self._timeout)
        return self._client

    async def health_check(self) -> bool:
        try:
            client = self._get_client()
            # Minimal list call to verify connectivity + auth
            await client.models.list()
            return True
        except Exception:
            return False

    async def complete(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> LLMResponse:
        try:
            client = self._get_client()
            oai_messages = [
                {"role": m.role, "content": m.content} for m in messages
            ]
            kwargs: Dict[str, Any] = {
                "model": model or self._default_model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": oai_messages,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = await client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            return LLMResponse(
                content=choice.message.content or "",
                model=response.model,
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
                finish_reason=choice.finish_reason or "stop",
            )
        except Exception as exc:
            from core.base.exceptions import ProviderException
            raise ProviderException(
                f"OpenAI completion failed: {exc}",
                provider_name=self.provider_name,
                operation="complete",
            ) from exc

    async def complete_with_vision(
        self,
        system_prompt: str,
        user_prompt: str,
        image_bytes: bytes,
        model: Optional[str] = None,
        json_mode: bool = True,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        try:
            client = self._get_client()
            b64_image = base64.b64encode(image_bytes).decode("utf-8")
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                        },
                    ],
                },
            ]
            kwargs: Dict[str, Any] = {
                "model": model or self._default_model,
                "temperature": 0.0,
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = await client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            return LLMResponse(
                content=choice.message.content or "",
                model=response.model,
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
                finish_reason=choice.finish_reason or "stop",
            )
        except Exception as exc:
            from core.base.exceptions import ProviderException
            raise ProviderException(
                f"OpenAI vision completion failed: {exc}",
                provider_name=self.provider_name,
                operation="complete_with_vision",
            ) from exc

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import yaml
from pathlib import Path

from sqlalchemy.orm import Session

from app.tools.audit_tool import log_audit, update_workflow_stage, complete_workflow_stage

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class AgentState(dict):
    """Typed workflow state passed between agents."""

    def set_status(self, status: str) -> "AgentState":
        self["status"] = status
        return self

    def set_error(self, error: str) -> "AgentState":
        self["error"] = error
        return self

    def set_next_agent(self, agent: str) -> "AgentState":
        self["next_agent"] = agent
        return self

    @property
    def document_id(self) -> str:
        return self.get("document_id", "")

    @property
    def file_path(self) -> str:
        return self.get("file_path", "")

    @property
    def status(self) -> str:
        return self.get("status", "PENDING")

    @property
    def next_agent(self) -> Optional[str]:
        return self.get("next_agent")


class BaseAgent(ABC):
    """
    All agents extend this base.
    Contract:
      - Input: AgentState
      - Output: AgentState
      - Writes audit log for every decision
      - Updates workflow progress
    """

    name: str = "BaseAgent"
    progress_on_entry: int = 0
    progress_on_exit: int = 10

    def __init__(self, db: Session):
        self.db = db
        self.logger = logging.getLogger(f"agent.{self.name}")

    def run(self, state: AgentState) -> AgentState:
        """Entry point. Wraps _execute with logging and error handling."""
        # document_id may be empty for the INTAKE agent (it creates the document).
        document_id = state.document_id or None

        self.logger.info(f"[{self.name}] Starting for document {document_id or '(new)'}")

        try:
            # Only touch workflow/audit tables if the document already exists.
            # Placed inside the try block so a DB/library error here is caught
            # and marks the doc FAILED rather than crashing the whole pipeline.
            if document_id:
                update_workflow_stage(
                    self.db,
                    document_id=document_id,
                    stage=self.name,
                    agent=self.name,
                    progress_percent=self.progress_on_entry,
                )
                log_audit(
                    self.db,
                    document_id=document_id,
                    entity_type="WORKFLOW",
                    entity_id=document_id,
                    action="AGENT_STARTED",
                    agent=self.name,
                    log_metadata={"state_keys": list(state.keys())},
                    stage=self.name,
                )

            result_state = self._execute(state)

            # Re-read the document_id — intake sets it during _execute.
            final_document_id = result_state.document_id or None

            if final_document_id:
                complete_workflow_stage(
                    self.db,
                    document_id=final_document_id,
                    agent=self.name,
                    stage_details={"outcome": result_state.get("status")},
                )
                log_audit(
                    self.db,
                    document_id=final_document_id,
                    entity_type="WORKFLOW",
                    entity_id=final_document_id,
                    action="AGENT_COMPLETED",
                    agent=self.name,
                    after_state={"status": result_state.get("status"), "next": result_state.get("next_agent")},
                    stage=self.name,
                )

            self.db.commit()
            self.logger.info(f"[{self.name}] Completed for document {final_document_id or '(none)'}")
            return result_state

        except Exception as exc:
            self.logger.error(f"[{self.name}] Error for document {document_id}: {exc}", exc_info=True)
            self.db.rollback()
            try:
                err_doc_id = state.document_id or None
                if err_doc_id:
                    from app.models.models import Document, DocumentStatus, WorkflowState
                    log_audit(
                        self.db,
                        document_id=err_doc_id,
                        entity_type="WORKFLOW",
                        entity_id=err_doc_id,
                        action="AGENT_FAILED",
                        agent=self.name,
                        log_metadata={"error": str(exc)},
                        stage=self.name,
                    )
                    # Mark document + workflow as FAILED so the UI stops showing PROCESSING
                    doc = self.db.query(Document).filter(Document.id == err_doc_id).first()
                    if doc:
                        doc.status = DocumentStatus.FAILED
                    ws = self.db.query(WorkflowState).filter(WorkflowState.document_id == err_doc_id).first()
                    if ws:
                        ws.error_message = f"{self.name}: {exc}"
                    self.db.commit()
            except Exception:
                self.db.rollback()
            state.set_status("FAILED")
            state.set_error(str(exc))
            return state

    @abstractmethod
    def _execute(self, state: AgentState) -> AgentState:
        """Agent-specific logic. Must return updated state."""

    @staticmethod
    def load_prompt(prompt_name: str) -> Dict[str, Any]:
        prompt_file = PROMPTS_DIR / f"{prompt_name}.yaml"
        with open(prompt_file, "r") as f:
            return yaml.safe_load(f)

    @staticmethod
    def _openai_client():
        from openai import OpenAI
        from app.core.config import settings
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not configured in the environment / .env")
        return OpenAI(api_key=settings.OPENAI_API_KEY)

    @staticmethod
    def _openai_call_with_retry(fn, max_retries: int = 4):
        """Call an OpenAI API function with exponential back-off on rate-limit errors."""
        import time
        import openai
        for attempt in range(max_retries):
            try:
                return fn()
            except openai.RateLimitError:
                if attempt == max_retries - 1:
                    raise
                wait = (2 ** attempt) * 5   # 5 → 10 → 20 → 40 s
                logger.warning("OpenAI rate limit hit; retrying in %ss (attempt %d/%d)",
                               wait, attempt + 1, max_retries)
                time.sleep(wait)
            except openai.APITimeoutError:
                if attempt == max_retries - 1:
                    raise
                time.sleep(5)

    @staticmethod
    def _repair_truncated_json(s: str) -> Dict[str, Any]:
        """
        Repair a JSON string cut off mid-stream.

        Three attempts in order:
          1. Close any open string quote, then close all open brackets.
             Handles the common case: truncation inside a string VALUE.
          2. Strip back to the last position where a complete element ended
             (after a '}', ']', or a comma between items), then close brackets.
             Handles truncation inside a KEY name (which leaves an orphan key).
          3. Walk backward to find the last complete '}' or ']' and close from there.
             Last-resort fallback.
        """
        # ── Pass 1: collect parse state ──────────────────────────────────────
        in_str = False
        esc = False
        stack: list[str] = []
        # last_safe: index of the end of the last "safe" chunk (complete element,
        # closing bracket, or the index of a comma — we'll rstrip it later).
        last_safe = 0

        i = 0
        while i < len(s):
            c = s[i]
            if esc:
                esc = False; i += 1; continue
            if c == '\\' and in_str:
                esc = True; i += 1; continue
            if c == '"':
                if in_str:
                    in_str = False
                    # Mark safe only when this closing quote ends a VALUE
                    # (next non-space char is not ':').
                    j = i + 1
                    while j < len(s) and s[j] in ' \t\r\n':
                        j += 1
                    if j >= len(s) or s[j] != ':':
                        last_safe = i + 1
                else:
                    in_str = True
                i += 1; continue
            if in_str:
                i += 1; continue
            # Outside strings:
            if c in '{[':
                stack.append(c)
            elif c in '}]' and stack:
                stack.pop()
                last_safe = i + 1
            elif c == ',' and stack:
                # Position of comma — s[:i] gives everything before it.
                last_safe = i
            i += 1

        def _recount_stack(text: str) -> list[str]:
            stk: list[str] = []
            s_in = False; s_esc = False
            for ch in text:
                if s_esc:
                    s_esc = False; continue
                if ch == '\\' and s_in:
                    s_esc = True; continue
                if ch == '"':
                    s_in = not s_in; continue
                if s_in:
                    continue
                if ch in '{[':
                    stk.append(ch)
                elif ch in '}]' and stk:
                    stk.pop()
            return stk

        def _close(text: str, stk: list) -> str:
            suffix = ''.join('}' if c == '{' else ']' for c in reversed(stk))
            return text.rstrip(',').rstrip() + suffix

        # ── Attempt 1: close open string (if any) + close brackets ───────────
        # If the last char was a backslash (esc=True), adding '"' produces '\"'
        # which keeps the string open. Drop the dangling backslash instead.
        if in_str and esc:
            a1 = s[:-1] + '"'
        elif in_str:
            a1 = s + '"'
        else:
            a1 = s
        try:
            return json.loads(_close(a1, stack))
        except json.JSONDecodeError:
            pass

        # ── Attempt 2: strip to last safe position + close remaining stack ───
        if last_safe > 0:
            a2 = s[:last_safe]
            try:
                return json.loads(_close(a2, _recount_stack(a2)))
            except json.JSONDecodeError:
                pass

        # ── Attempt 3: walk backward to find last complete bracket ───────────
        for k in range(len(s) - 1, -1, -1):
            if s[k] in '}]':
                candidate = s[:k + 1]
                try:
                    return json.loads(_close(candidate, _recount_stack(candidate)))
                except json.JSONDecodeError:
                    continue

        raise json.JSONDecodeError("Could not repair JSON", s, len(s))

    @staticmethod
    def _call_openai_json(
        system_prompt: str,
        user_prompt: str,
        model: str = "gpt-4o",
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        client = BaseAgent._openai_client()

        def _call(tokens: int = max_tokens):
            response = client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            choice = response.choices[0]
            content = choice.message.content or ""

            if choice.finish_reason == "length":
                logger.warning(
                    "OpenAI response truncated (finish_reason=length, content_len=%d, "
                    "token_limit=%d); attempting JSON repair", len(content), tokens
                )

            # Always try json.loads first; on ANY parse failure, attempt repair
            # then retry with a larger token budget. This catches both
            # finish_reason="length" (hard cut-off) and rare cases where the
            # model stops mid-JSON even with finish_reason="stop".
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                logger.warning(
                    "JSON parse failed (finish_reason=%s, content_len=%d); "
                    "attempting repair", choice.finish_reason, len(content)
                )
                try:
                    return BaseAgent._repair_truncated_json(content)
                except json.JSONDecodeError:
                    if tokens < 16384:
                        new_tokens = min(tokens * 2, 16384)
                        logger.warning(
                            "JSON repair failed; retrying with %d tokens", new_tokens
                        )
                        return _call(new_tokens)
                    raise

        return BaseAgent._openai_call_with_retry(lambda: _call())

    @staticmethod
    def _call_openai_vision_json(
        system_prompt: str,
        user_prompt: str,
        image_bytes: bytes,
        model: str = "gpt-4o",
    ) -> Dict[str, Any]:
        import base64
        client = BaseAgent._openai_client()
        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        def _call():
            response = client.chat.completions.create(
                model=model,
                temperature=0.0,
                max_tokens=512,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}},
                        ],
                    },
                ],
            )
            return json.loads(response.choices[0].message.content)

        return BaseAgent._openai_call_with_retry(_call)

    @staticmethod
    def _call_openai_vision_text(
        system_prompt: str,
        user_prompt: str,
        image_bytes: bytes,
        model: str = "gpt-4o",
    ) -> str:
        import base64
        client = BaseAgent._openai_client()
        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        def _call():
            response = client.chat.completions.create(
                model=model,
                temperature=0.0,
                max_tokens=4096,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}},
                        ],
                    },
                ],
            )
            return response.choices[0].message.content

        return BaseAgent._openai_call_with_retry(_call)
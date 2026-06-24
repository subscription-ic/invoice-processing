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

        # Only touch workflow/audit tables if the document already exists.
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

        try:
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
    def _call_openai_json(
        system_prompt: str,
        user_prompt: str,
        model: str = "gpt-4o",
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        client = BaseAgent._openai_client()
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return json.loads(response.choices[0].message.content)

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
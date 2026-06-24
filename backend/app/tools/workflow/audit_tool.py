"""AuditTool — write immutable audit events for compliance-relevant decisions."""
from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Dict, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class AuditEventInput(ToolInput):
    document_id: str
    entity_type: str
    entity_id: str
    action: str
    agent_name: str
    user_id: Optional[str] = None
    before_state: Optional[Dict[str, Any]] = None
    after_state: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    stage: Optional[str] = None


class AuditEventOutput(ToolOutput):
    audit_id: Optional[str] = None
    chain_hash: Optional[str] = None
    error_code: Optional[str] = None


class AuditTool(BaseTool[AuditEventInput, AuditEventOutput]):
    name: ClassVar[str] = "audit"
    description: ClassVar[str] = "Write an immutable audit event for compliance tracking"
    input_model: ClassVar = AuditEventInput
    output_model: ClassVar = AuditEventOutput

    def __init__(self, audit_repository=None, **kwargs):
        super().__init__(**kwargs)
        self._repo = audit_repository

    def _get_repo(self):
        if self._repo is None:
            from core.container import get_container
            self._repo = get_container().audit_repository
        return self._repo

    def _execute(self, input_data: AuditEventInput) -> AuditEventOutput:
        try:
            repo = self._get_repo()
            loop = asyncio.get_event_loop()
            audit_log = loop.run_until_complete(repo.append_event(
                document_id=input_data.document_id,
                entity_type=input_data.entity_type,
                entity_id=input_data.entity_id,
                action=input_data.action,
                agent_name=input_data.agent_name,
                user_id=input_data.user_id,
                before_state=input_data.before_state,
                after_state=input_data.after_state,
                metadata=input_data.metadata,
                stage=input_data.stage,
            ))
            chain_hash = None
            if audit_log and hasattr(audit_log, "log_metadata") and audit_log.log_metadata:
                chain_hash = audit_log.log_metadata.get("chain_hash")
            return AuditEventOutput(
                success=True,
                audit_id=str(audit_log.id) if audit_log else None,
                chain_hash=chain_hash,
            )
        except Exception as exc:
            # Audit failures should never crash the pipeline — just log
            return AuditEventOutput(
                success=False,
                error_code="AUDIT_WRITE_FAILED",
                error_message=str(exc),
            )

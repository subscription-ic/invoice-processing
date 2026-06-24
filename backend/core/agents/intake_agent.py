"""
IntakeAgent — first agent in the pipeline.

Receives raw file bytes via constructor (passed by the upload endpoint / graph node).
Validates, hashes, and uploads to storage, then returns updated WorkflowState.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, Optional

from core.base.agent import BaseAgent
from core.state.workflow_state import WorkflowState


class IntakeAgent(BaseAgent):
    name: ClassVar[str] = "intake_agent"

    def __init__(
        self,
        file_bytes: Optional[bytes] = None,
        original_filename: Optional[str] = None,
        file_tool=None,
        hash_tool=None,
        storage_tool=None,
        audit_tool=None,
        config: Optional[Dict[str, Any]] = None,
        logger=None,
    ) -> None:
        super().__init__(tools={}, config=config, logger=logger)
        self._file_bytes = file_bytes
        self._original_filename = original_filename
        self._file_tool = file_tool
        self._hash_tool = hash_tool
        self._storage_tool = storage_tool
        self._audit_tool = audit_tool

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.document.file_tool import FileTool, FileValidationInput
        from app.tools.document.hash_tool import HashTool, HashInput
        from app.tools.document.storage_tool import StorageTool, StorageUploadInput
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

        file_tool = self._file_tool or FileTool()
        hash_tool = self._hash_tool or HashTool()
        storage_tool = self._storage_tool or StorageTool()
        audit_tool = self._audit_tool or AuditTool()

        doc_id = state.workflow.document_id
        tenant_id = state.workflow.tenant_id
        file_bytes = self._file_bytes
        filename = self._original_filename or "upload.pdf"

        if not file_bytes:
            return state.with_error("NO_FILE_CONTENT", "No file bytes provided to IntakeAgent", self.name)

        # 1. File validation
        validation = file_tool.run(FileValidationInput(
            file_bytes=file_bytes,
            filename=filename,
            tenant_id=tenant_id,
        ))
        if not validation.is_valid:
            return state.with_error(
                validation.error_code or "FILE_INVALID",
                validation.error_message or "File validation failed",
                self.name,
            )

        # 2. Hash
        hash_result = hash_tool.run(HashInput(content=file_bytes, document_id=doc_id))

        # 3. Upload to storage
        upload_result = storage_tool.upload(StorageUploadInput(
            file_bytes=file_bytes,
            document_id=doc_id,
            tenant_id=tenant_id,
            original_filename=filename,
            content_type=validation.detected_mime or "application/pdf",
        ))

        # 4. Audit event
        audit_tool.run(AuditEventInput(
            document_id=doc_id,
            entity_type="DOCUMENT",
            entity_id=doc_id,
            action="DOCUMENT_INGESTED",
            agent_name=self.name,
            after_state={
                "filename": filename,
                "sha256": hash_result.sha256,
                "size_bytes": hash_result.size_bytes,
                "storage_path": upload_result.storage_path if upload_result.success else None,
            },
            stage="INTAKE",
        ))

        new_doc = state.document.model_copy(update={
            "original_filename": filename,
            "file_hash": hash_result.sha256,
            "file_size_bytes": hash_result.size_bytes,
            "mime_type": validation.detected_mime,
            "storage_path": upload_result.storage_path if upload_result.success else None,
            "upload_timestamp": datetime.now(timezone.utc),
        })

        return state.model_copy(deep=True, update={
            "document": new_doc,
            "workflow": state.workflow.model_copy(update={
                "status": "PROCESSING",
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })

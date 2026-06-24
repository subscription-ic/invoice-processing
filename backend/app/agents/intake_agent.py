from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.agents.base import AgentState, BaseAgent
from app.core.config import settings
from app.models.models import Document, DocumentStatus, WorkflowState, ProcessingStage
from app.services.storage.local_storage import get_storage
from app.tools.audit_tool import log_audit, update_workflow_stage
from app.tools.file_validation import validate_file


class IntakeAgent(BaseAgent):
    """
    Agent 1: INTAKE
    Responsibilities:
    - Validate the file (size, extension, magic bytes)
    - Generate unique document_id
    - Store raw file
    - Create Document record
    - Create WorkflowState
    - Write audit log
    - Route to DOCUMENT_CLASSIFICATION
    """

    name = "INTAKE_AGENT"
    progress_on_entry = 0
    progress_on_exit = 8

    def _execute(self, state: AgentState) -> AgentState:
        content: bytes = state["file_content"]
        filename: str = state["filename"]
        uploaded_by: str = state["uploaded_by"]

        # ── File Validation ────────────────────────────────────────────────────
        is_valid, error_msg, file_meta = validate_file(filename, content)

        if not is_valid:
            log_audit(
                self.db,
                entity_type="DOCUMENT",
                action="INTAKE_REJECTED",
                agent=self.name,
                log_metadata={"filename": filename, "error": error_msg, **file_meta},
            )
            state.set_status("REJECTED")
            state.set_error(error_msg)
            return state

        # ── Generate Document ID ───────────────────────────────────────────────
        document_id = f"DOC-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
        ext = Path(filename).suffix.lstrip(".").lower()

        # ── Store Raw File ─────────────────────────────────────────────────────
        storage = get_storage()
        raw_rel_path = storage.raw_path(document_id, ext)
        full_raw_path = str(Path(settings.UPLOAD_DIR) / raw_rel_path)

        Path(full_raw_path).parent.mkdir(parents=True, exist_ok=True)
        with open(full_raw_path, "wb") as f:
            f.write(content)

        # ── Create Document Record ─────────────────────────────────────────────
        doc = Document(
            document_id=document_id,
            filename=f"{document_id}.{ext}",
            original_filename=filename,
            file_extension=ext,
            file_size=file_meta["file_size"],
            mime_type=file_meta.get("mime_type", "application/octet-stream"),
            checksum=file_meta["checksum"],
            original_path=full_raw_path,
            status=DocumentStatus.PROCESSING,
            currency="INR",
            ingestion_source=state.get("ingestion_source", "PORTAL"),
            uploaded_by=uploaded_by,
            processing_started_at=datetime.now(timezone.utc),
        )
        self.db.add(doc)
        self.db.flush()

        # ── Create Workflow State ──────────────────────────────────────────────
        workflow = WorkflowState(
            document_id=doc.id,
            current_stage=ProcessingStage.DOCUMENT_CLASSIFICATION,
            current_agent=self.name,
            progress_percent=8,
            stage_history=[],
        )
        self.db.add(workflow)
        self.db.flush()

        log_audit(
            self.db,
            document_id=doc.id,
            entity_type="DOCUMENT",
            entity_id=doc.id,
            action="DOCUMENT_INGESTED",
            agent=self.name,
            after_state={
                "document_id": document_id,
                "filename": filename,
                "file_size": file_meta["file_size"],
                "checksum": file_meta["checksum"],
            },
            stage=ProcessingStage.INTAKE,
        )

        state["document_db_id"] = doc.id
        state["document_id"] = doc.id
        state["document_ref_id"] = document_id
        state["file_path"] = full_raw_path
        state["file_extension"] = ext
        state.set_status("SUCCESS")
        state.set_next_agent("CLASSIFICATION_AGENT")

        update_workflow_stage(
            self.db,
            document_id=doc.id,
            stage=ProcessingStage.DOCUMENT_CLASSIFICATION,
            agent=self.name,
            progress_percent=8,
        )

        return state
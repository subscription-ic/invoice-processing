from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.models import AuditLog, WorkflowState, ProcessingStage


def log_audit(
    db: Session,
    *,
    document_id: Optional[str] = None,
    entity_type: str,
    entity_id: Optional[str] = None,
    action: str,
    agent: Optional[str] = None,
    user_id: Optional[str] = None,
    before_state: Optional[Dict[str, Any]] = None,
    after_state: Optional[Dict[str, Any]] = None,
    log_metadata: Optional[Dict[str, Any]] = None,
    stage: Optional[str] = None,
) -> AuditLog:
    """Write an immutable audit record."""
    log = AuditLog(
        document_id=document_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        agent=agent,
        user_id=user_id,
        before_state=before_state,
        after_state=after_state,
        log_metadata=log_metadata or {},
        stage=stage,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(log)
    db.flush()
    return log


def update_workflow_stage(
    db: Session,
    document_id: str,
    stage: str,
    agent: str,
    progress_percent: int,
    error_message: Optional[str] = None,
    stage_details: Optional[Dict[str, Any]] = None,
) -> WorkflowState:
    """Update the workflow state and append to stage history."""
    state = db.query(WorkflowState).filter(WorkflowState.document_id == document_id).first()
    if not state:
        state = WorkflowState(document_id=document_id)
        db.add(state)

    now = datetime.now(timezone.utc)

    # Append to stage history
    history = list(state.stage_history or [])
    history.append({
        "stage": stage,
        "agent": agent,
        "started_at": now.isoformat(),
        "progress_percent": progress_percent,
        "status": "ERROR" if error_message else "RUNNING",
        "error": error_message,
        "details": stage_details or {},
    })

    state.current_stage = stage
    state.current_agent = agent
    state.progress_percent = progress_percent
    state.error_message = error_message
    state.stage_history = history
    state.updated_at = now

    if stage == ProcessingStage.COMPLETED:
        state.completed_at = now

    db.flush()
    return state


def complete_workflow_stage(
    db: Session,
    document_id: str,
    agent: str,
    stage_details: Optional[Dict[str, Any]] = None,
) -> None:
    """Mark the last stage in workflow history as completed."""
    state = db.query(WorkflowState).filter(WorkflowState.document_id == document_id).first()
    if not state:
        return
    history = list(state.stage_history or [])
    if history:
        history[-1]["status"] = "COMPLETED"
        history[-1]["completed_at"] = datetime.now(timezone.utc).isoformat()
        if stage_details:
            history[-1]["details"].update(stage_details)
        state.stage_history = history
    db.flush()
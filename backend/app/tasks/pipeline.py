from __future__ import annotations

import logging
from typing import Any, Dict

from celery import Task
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.core.database import SyncSessionLocal
from app.agents.base import AgentState

logger = logging.getLogger(__name__)


def _get_db():
    return SyncSessionLocal()


# Keys that hold binary/large data — never return these in the Celery result.
_HEAVY_KEYS = {"file_content", "image_bytes", "ocr_text", "extracted_data", "handwriting_result"}


def _clean_state(state) -> Dict[str, Any]:
    """Return a JSON-safe, lightweight copy of the agent state for Celery results."""
    out = {}
    for k, v in dict(state).items():
        if k in _HEAVY_KEYS:
            continue
        if isinstance(v, (bytes, bytearray)):
            continue
        out[k] = v
    return out


def execute_pipeline(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pure Python function — the actual pipeline logic, no Celery machinery.

    Call this directly from threads or synchronous code. The Celery task
    `run_document_pipeline` below is a thin wrapper around this function
    for when a real Celery worker is running.
    """
    from app.agents.intake_agent import IntakeAgent
    from app.agents.classification_agent import ClassificationAgent
    from app.agents.ocr_agent import OCRAgent
    from app.agents.handwriting_agent import HandwritingAgent
    from app.agents.extraction_agent import ExtractionAgent
    from app.agents.universal_validation_agent import UniversalValidationAgent
    from app.agents.business_profile_agent import BusinessProfileAgent
    from app.agents.profile_validation_agent import ProfileValidationAgent
    from app.agents.matching_agent import MatchingAgent
    from app.agents.exception_agent import ExceptionAgent
    from app.agents.approval_agent import ApprovalAgent
    from app.agents.erp_posting_agent import ERPPostingAgent
    from app.agents.payment_agent import PaymentAgent

    AGENT_MAP = {
        "CLASSIFICATION_AGENT": ClassificationAgent,
        "OCR_AGENT": OCRAgent,
        "HANDWRITING_AGENT": HandwritingAgent,
        "EXTRACTION_AGENT": ExtractionAgent,
        "UNIVERSAL_VALIDATION_AGENT": UniversalValidationAgent,
        "BUSINESS_PROFILE_AGENT": BusinessProfileAgent,
        "PROFILE_VALIDATION_AGENT": ProfileValidationAgent,
        "MATCHING_AGENT": MatchingAgent,
        "EXCEPTION_AGENT": ExceptionAgent,
        "APPROVAL_AGENT": ApprovalAgent,
        "ERP_POSTING_AGENT": ERPPostingAgent,
        "PAYMENT_AGENT": PaymentAgent,
    }

    agent_state = AgentState(state)
    db = _get_db()

    try:
        # ── Stage 1: Intake (skipped when the API already created the document) ──
        if agent_state.get("skip_intake"):
            agent_state.set_next_agent("CLASSIFICATION_AGENT")
        else:
            intake = IntakeAgent(db)
            agent_state = intake.run(agent_state)
            if agent_state.status in ("REJECTED", "FAILED"):
                return _clean_state(agent_state)

        # ── Stage 2+: Follow agent routing ────────────────────────────────────
        max_iterations = 15
        iteration = 0

        while agent_state.next_agent and iteration < max_iterations:
            iteration += 1
            next_agent_name = agent_state.next_agent

            if next_agent_name not in AGENT_MAP:
                logger.error("Unknown agent: %s", next_agent_name)
                break

            AgentClass = AGENT_MAP[next_agent_name]
            agent = AgentClass(db)
            agent_state = agent.run(agent_state)

            if agent_state.status in ("HUMAN_REVIEW_REQUIRED", "COMPLETED", "PENDING_APPROVAL"):
                break

            if agent_state.status == "FAILED":
                logger.error("Pipeline failed at %s: %s", next_agent_name, agent_state.get("error"))
                break

        return _clean_state(agent_state)

    except SQLAlchemyError as exc:
        logger.error("Database error in pipeline: %s", exc, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        _doc_id = state.get("document_id")
        if _doc_id:
            try:
                _fresh = _get_db()
                try:
                    from app.models.models import Document, DocumentStatus, WorkflowState
                    _d = _fresh.query(Document).filter(Document.id == _doc_id).first()
                    if _d and _d.status == DocumentStatus.PROCESSING:
                        _d.status = DocumentStatus.FAILED
                    _ws = _fresh.query(WorkflowState).filter(
                        WorkflowState.document_id == _doc_id
                    ).first()
                    if _ws:
                        _ws.error_message = f"DB error: {exc}"
                    _fresh.commit()
                finally:
                    _fresh.close()
            except Exception:
                pass
        raise

    except Exception as exc:
        logger.error("Unexpected pipeline error: %s", exc, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        raise

    finally:
        try:
            db.close()
        except Exception:
            pass


@celery_app.task(
    name="app.tasks.pipeline.run_document_pipeline",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue="pipeline",
    acks_late=True,
)
def run_document_pipeline(self: Task, state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Celery task wrapper around execute_pipeline.
    Only used when a real Celery worker is running.
    Direct (in-process) callers should use execute_pipeline() instead —
    Celery's __call__ machinery requires request_stack to be initialized
    by the worker, which never happens in plain threads.
    """
    return execute_pipeline(state)


def execute_post_approval_pipeline(document_id: str) -> Dict[str, Any]:
    """
    Pure Python — run ERP posting and payment after a human approval.
    Call this directly from threads; never call the Celery task directly.
    """
    from app.agents.erp_posting_agent import ERPPostingAgent
    from app.agents.payment_agent import PaymentAgent

    db = _get_db()
    try:
        state = AgentState({"document_id": document_id})

        erp_agent = ERPPostingAgent(db)
        state = erp_agent.run(state)

        if state.status not in ("FAILED",):
            payment_agent = PaymentAgent(db)
            state = payment_agent.run(state)

        return dict(state)
    except Exception as exc:
        logger.exception("Post-approval pipeline failed for document %s: %s", document_id, exc)
        return {"error": str(exc)}
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.pipeline.run_post_approval_pipeline",
    queue="pipeline",
)
def run_post_approval_pipeline(document_id: str) -> Dict[str, Any]:
    """Celery wrapper — delegates to execute_post_approval_pipeline."""
    return execute_post_approval_pipeline(document_id)


@celery_app.task(name="app.tasks.pipeline.update_payment_statuses", queue="default")
def update_payment_statuses() -> None:
    """Daily task to mark overdue payments."""
    from datetime import date
    from app.models.models import PaymentSchedule, PaymentStatus

    db = _get_db()
    try:
        today = date.today()
        overdue = (
            db.query(PaymentSchedule)
            .filter(
                PaymentSchedule.due_date < today,
                PaymentSchedule.status == PaymentStatus.SCHEDULED,
            )
            .all()
        )
        for ps in overdue:
            ps.status = PaymentStatus.OVERDUE
        db.commit()
        logger.info(f"Marked {len(overdue)} payments as overdue")
    finally:
        db.close()
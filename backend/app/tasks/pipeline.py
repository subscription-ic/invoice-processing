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
    Main pipeline task. Orchestrates all 12 agents sequentially.
    State is passed between agents as a dict.
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
    from app.models.models import BusinessProfile, DocType

    agent_state = AgentState(state)
    db = _get_db()

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
                logger.error(f"Unknown agent: {next_agent_name}")
                break

            AgentClass = AGENT_MAP[next_agent_name]
            agent = AgentClass(db)
            agent_state = agent.run(agent_state)

            # Stop if human review required or completed
            if agent_state.status in ("HUMAN_REVIEW_REQUIRED", "COMPLETED", "PENDING_APPROVAL"):
                break

            if agent_state.status == "FAILED":
                logger.error(f"Pipeline failed at {next_agent_name}: {agent_state.get('error')}")
                break

        return _clean_state(agent_state)

    except SQLAlchemyError as exc:
        logger.error(f"Database error in pipeline: {exc}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        self.retry(exc=exc)

    except Exception as exc:
        logger.error(f"Unexpected pipeline error: {exc}", exc_info=True)
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
    name="app.tasks.pipeline.run_post_approval_pipeline",
    queue="pipeline",
)
def run_post_approval_pipeline(document_id: str) -> Dict[str, Any]:
    """Trigger ERP posting and payment scheduling after approval."""
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
    finally:
        db.close()


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
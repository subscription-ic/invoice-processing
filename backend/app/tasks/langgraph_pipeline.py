"""
Celery task — run the LangGraph InvoiceProcessingGraph.

Activated when feature flag USE_LANGGRAPH_PIPELINE=true.
The file has already been saved to disk by the FastAPI upload endpoint;
this task builds the initial WorkflowState and invokes the graph.

On graph interrupt (HITL pause): state is checkpointed by LangGraph automatically.
  DB document status is updated to the value in state.workflow.status.
On graph completion: same — DB updated from state.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(
    bind=True,
    name="tasks.run_langgraph_pipeline",
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def run_langgraph_pipeline(
    self,
    document_db_id: str,
    file_path: str,
    file_extension: str,
    user_id: str,
    tenant_id: str = "default",
    source_channel: str = "PORTAL",
) -> dict:
    """
    Main LangGraph invoice pipeline task.

    Args:
        document_db_id: The DB primary key (UUID string) of the Document row.
        file_path:       Absolute path to the uploaded file on disk.
        file_extension:  File extension without dot (pdf, jpg, …).
        user_id:         ID of the user who uploaded the document.
        tenant_id:       Tenant ID (from X-Tenant-ID header, default "default").
        source_channel:  Ingestion channel (PORTAL, EMAIL, API, …).
    """
    from app.core.graph_registry import GraphRegistry
    from core.state.workflow_state import (
        WorkflowMetadata, DocumentInfo, WorkflowState,
    )

    registry = GraphRegistry.get_instance()
    if not registry.is_ready():
        registry.startup()

    # Build initial WorkflowState
    initial_state = WorkflowState(
        workflow=WorkflowMetadata(
            document_id=document_db_id,
            tenant_id=tenant_id,
            status="UPLOADED",
            current_agent="invoice_processing_graph",
            uploaded_by=user_id,
            source_channel=source_channel,
            processing_graph="invoice_processing",
        ),
        document=DocumentInfo(
            id=document_db_id,
            storage_path=file_path,
            original_filename=f"document.{file_extension}",
            mime_type=_mime_from_ext(file_extension),
            upload_timestamp=datetime.now(timezone.utc),
        ),
    )

    config = {"configurable": {"thread_id": document_db_id}}

    try:
        graph = registry.get_graph("invoice_processing")
        result_state = graph.invoke(initial_state, config=config)

        # Update DB from result state
        if isinstance(result_state, WorkflowState):
            _sync_state_to_db(document_db_id, result_state)
        return {"status": "ok", "document_id": document_db_id}

    except Exception as exc:
        exc_name = type(exc).__name__
        # Gracefully handle LangGraph HITL interrupts
        if "Interrupt" in exc_name or "NodeInterrupt" in exc_name:
            logger.info(f"Graph interrupted for doc {document_db_id} (HITL pause): {exc_name}")
            # Checkpoint was already saved by LangGraph before interrupt
            # Try to read current state and sync to DB
            try:
                snapshot = registry.get_state("invoice_processing", document_db_id)
                if snapshot and snapshot.values and isinstance(snapshot.values, WorkflowState):
                    _sync_state_to_db(document_db_id, snapshot.values)
            except Exception:
                pass
            return {"status": "interrupted", "document_id": document_db_id}

        logger.error(f"LangGraph pipeline failed for doc {document_db_id}: {exc}", exc_info=True)
        _mark_db_failed(document_db_id, str(exc))
        raise self.retry(exc=exc)


def _mime_from_ext(ext: str) -> str:
    return {
        "pdf": "application/pdf",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "tiff": "image/tiff",
        "tif": "image/tiff",
    }.get(ext.lower(), "application/octet-stream")


def _sync_state_to_db(document_db_id: str, state) -> None:
    """Best-effort: update Document.status from completed WorkflowState."""
    try:
        import asyncio
        from sqlalchemy import select, update
        from app.core.database import async_session_factory
        from app.models.models import Document, DocumentStatus

        _STATUS_MAP = {
            "PAYMENT_SCHEDULED": DocumentStatus.PAYMENT_SCHEDULED,
            "APPROVED": DocumentStatus.APPROVED,
            "REJECTED": DocumentStatus.REJECTED,
            "EXCEPTION": DocumentStatus.EXCEPTION,
            "AWAITING_APPROVAL": DocumentStatus.AWAITING_APPROVAL,
            "UNDER_REVIEW": DocumentStatus.UNDER_REVIEW,
            "RETRY_EXHAUSTED": DocumentStatus.EXCEPTION,
        }

        wf_status = state.workflow.status if hasattr(state, "workflow") else None
        db_status = _STATUS_MAP.get(wf_status, DocumentStatus.PROCESSING)

        async def _update():
            async with async_session_factory() as session:
                async with session.begin():
                    await session.execute(
                        update(Document)
                        .where(Document.id == document_db_id)
                        .values(status=db_status, updated_at=datetime.now(timezone.utc))
                    )

        asyncio.run(_update())
    except Exception as e:
        logger.warning(f"Could not sync LangGraph state to DB for {document_db_id}: {e}")


def _mark_db_failed(document_db_id: str, error: str) -> None:
    """Best-effort: mark the document as EXCEPTION in the DB."""
    try:
        import asyncio
        from sqlalchemy import update
        from app.core.database import async_session_factory
        from app.models.models import Document, DocumentStatus

        async def _update():
            async with async_session_factory() as session:
                async with session.begin():
                    await session.execute(
                        update(Document)
                        .where(Document.id == document_db_id)
                        .values(status=DocumentStatus.EXCEPTION, updated_at=datetime.now(timezone.utc))
                    )

        asyncio.run(_update())
    except Exception:
        pass

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from uuid import UUID

# Bounded pool — limits SIMULTANEOUS in-process pipelines so a small container
# can't be OOM-killed when many docs are uploaded at once. Extra uploads queue
# here and process as slots free (intake still returns 202 immediately).
_pipeline_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="pipeline")

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import bindparam, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.deps import resolve_document
from app.core.database import get_async_session
from app.core.security import get_current_user
from app.models.models import Document, DocumentStatus, User, WorkflowState
from app.schemas.schemas import DocumentListOut, DocumentOut, DocumentUploadResponse, WorkflowStateOut

router = APIRouter(prefix="/documents", tags=["Documents"])

# Child tables referencing documents WITHOUT ondelete=CASCADE — must be cleared
# manually before deleting a document (the CASCADE-configured ones drop automatically).
_NONCASCADE_CHILDREN = [
    "audit_logs", "notifications", "workflow_state_archive", "workflow_timelines",
    "notification_logs", "retry_logs", "exception_resolution_history", "token_usage",
]


@router.post("/demo-reset")
async def demo_reset(
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    """Demo helper: delete all UPLOADED documents (DOC-101 and above), leaving the
    100 static seed documents (DOC-1..DOC-100) intact. Called by the UI once per
    browser session so uploads always restart from DOC-101."""
    # Keep the static demo data pristine: any seeded exceptions that were
    # auto-escalated by background jobs are reset back to OPEN (demo is static).
    await db.execute(text(
        "UPDATE exceptions SET status='OPEN', escalation_count=0, escalated_to=NULL, escalated_at=NULL "
        "WHERE status IN ('ESCALATED','IN_PROGRESS')"
    ))
    await db.commit()

    rows = (await db.execute(
        select(Document.id, Document.document_id).where(Document.document_id.like("DOC-%"))
    )).all()
    ids = []
    for _id, docnum in rows:
        suf = docnum.split("-", 1)[1] if "-" in docnum else ""
        if suf.isdigit() and int(suf) > 100:
            ids.append(str(_id))
    if not ids:
        return {"deleted": 0, "exceptions_reset": True}

    for tbl in _NONCASCADE_CHILDREN:
        stmt = text(f"DELETE FROM {tbl} WHERE document_id::text IN :ids").bindparams(
            bindparam("ids", expanding=True)
        )
        await db.execute(stmt, {"ids": ids})
    await db.execute(
        text("DELETE FROM documents WHERE id::text IN :ids").bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    )
    await db.commit()
    return {"deleted": len(ids)}


@router.post("/upload", response_model=DocumentUploadResponse, status_code=202)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    """
    Create the document and store the file synchronously (intake), then dispatch
    the rest of the pipeline to Celery by document_id. Returns the real document_id
    immediately so the UI can show live step-by-step progress.
    """
    import uuid as _uuid
    from datetime import datetime, timezone
    from pathlib import Path
    from app.tasks.pipeline import execute_pipeline
    from app.core.config import settings
    from app.tools.file_validation import validate_file
    from app.models.models import ProcessingStage
    from app.services.storage.local_storage import get_storage

    content = await file.read()

    # Validate
    is_valid, error_msg, meta = validate_file(file.filename or "unknown", content)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # Sequential demo-friendly IDs: static seed docs are DOC-1..DOC-100; uploads
    # continue from DOC-101. The demo-reset endpoint wipes uploads back to DOC-101.
    _rows = (await db.execute(select(Document.document_id).where(Document.document_id.like("DOC-%")))).all()
    _nums = []
    for (_did,) in _rows:
        _suf = _did.split("-", 1)[1] if "-" in _did else ""
        if _suf.isdigit():
            _nums.append(int(_suf))
    _next = max((max(_nums) + 1) if _nums else 101, 101)
    doc_ref = f"DOC-{_next}"
    ext = Path(file.filename or "f").suffix.lstrip(".").lower()
    storage = get_storage()
    rel_path = storage.raw_path(doc_ref, ext)
    full_path = str(Path(settings.UPLOAD_DIR) / rel_path)
    Path(full_path).parent.mkdir(parents=True, exist_ok=True)
    with open(full_path, "wb") as f:
        f.write(content)

    doc = Document(
        document_id=doc_ref,
        filename=f"{doc_ref}.{ext}",
        original_filename=file.filename or "unknown",
        file_extension=ext,
        file_size=meta["file_size"],
        mime_type=meta.get("mime_type"),
        checksum=meta["checksum"],
        original_path=full_path,
        status=DocumentStatus.PROCESSING,
        currency="INR",
        ingestion_source="PORTAL",
        uploaded_by=str(current_user.id),
        processing_started_at=datetime.now(timezone.utc),
    )
    db.add(doc)
    await db.flush()

    workflow = WorkflowState(
        document_id=doc.id,
        current_stage=ProcessingStage.DOCUMENT_CLASSIFICATION,
        current_agent="INTAKE_AGENT",
        progress_percent=8,
        stage_history=[{
            "stage": ProcessingStage.INTAKE,
            "agent": "INTAKE_AGENT",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "COMPLETED",
            "progress_percent": 8,
            "details": {"filename": file.filename, "size": meta["file_size"]},
        }],
    )
    db.add(workflow)
    await db.commit()

    state = {
        "document_id": doc.id,
        "document_db_id": doc.id,
        "document_ref_id": doc_ref,
        "file_path": full_path,
        "file_extension": ext,
        "skip_intake": True,
        "status": "SUCCESS",
    }

    task_id = f"thread-{doc_ref}"

    def _run_pipeline(pipeline_state: dict) -> None:
        import traceback as _tb
        _log = logging.getLogger("pipeline")
        try:
            execute_pipeline(pipeline_state)
        except Exception as _exc:
            _full_tb = _tb.format_exc()
            _log.error("Pipeline error for %s: %s\n%s", doc_ref, _exc, _full_tb)
            _doc_id = pipeline_state.get("document_id")
            if _doc_id:
                try:
                    from app.core.database import SyncSessionLocal
                    from app.models.models import Document, DocumentStatus, WorkflowState
                    _db = SyncSessionLocal()
                    try:
                        _doc = _db.query(Document).filter(Document.id == _doc_id).first()
                        if _doc and _doc.status == DocumentStatus.PROCESSING:
                            _doc.status = DocumentStatus.FAILED
                        _ws = _db.query(WorkflowState).filter(
                            WorkflowState.document_id == _doc_id
                        ).first()
                        if _ws and not _ws.error_message:
                            # Store the full traceback so the UI can show exactly
                            # which library line raises the error.
                            _ws.error_message = (
                                f"Pipeline crashed: {_exc}\n\n--- Traceback ---\n{_full_tb}"
                            )
                        _db.commit()
                    finally:
                        _db.close()
                except Exception as _db_exc:
                    _log.error("Could not mark doc %s as FAILED: %s", _doc_id, _db_exc)

    _pipeline_pool.submit(_run_pipeline, state)

    return DocumentUploadResponse(
        document_id=doc.id,
        filename=file.filename or "unknown",
        status="PROCESSING",
        task_id=task_id,
        message="Document queued for processing. Pipeline running in background.",
    )


@router.get("", response_model=List[DocumentListOut])
async def list_documents(
    status: Optional[str] = Query(None),
    business_profile: Optional[str] = Query(None),
    vendor_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    q = select(Document).options(selectinload(Document.vendor))
    if status:
        q = q.where(Document.status == status)
    if business_profile:
        q = q.where(Document.business_profile == business_profile)
    if vendor_id:
        q = q.where(Document.vendor_id == vendor_id)
    q = q.order_by(desc(Document.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    docs = result.scalars().all()
    return [
        DocumentListOut(
            id=str(d.id),
            document_id=d.document_id,
            original_filename=d.original_filename,
            status=d.status,
            doc_type=d.doc_type,
            business_profile=d.business_profile,
            vendor_id=str(d.vendor_id) if d.vendor_id else None,
            vendor_name=(d.vendor.name if d.vendor else None)
                        or ((d.extracted_data or {}).get("vendor", {}) or {}).get("name"),
            ai_profile_confidence=d.ai_profile_confidence,
            invoice_number=d.invoice_number,
            invoice_date=d.invoice_date,
            total_amount=d.total_amount,
            currency=d.currency,
            ingestion_source=d.ingestion_source,
            created_at=d.created_at,
        )
        for d in docs
    ]


@router.delete("/{document_id}", status_code=200)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a document, all its pipeline records (cascade), and storage files."""
    import os

    doc = await resolve_document(db, document_id)

    # Remove storage files (best-effort)
    for path in [doc.original_path, doc.ocr_path, doc.extracted_path, doc.final_path, doc.exception_path]:
        if path:
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception:
                pass

    # Use Core DELETE statements (NOT ORM db.delete, which lazy-loads relationships
    # and fails in an async session). DB-level ON DELETE CASCADE handles most children;
    # audit_logs and notifications have non-cascade FKs so we clear them explicitly.
    from app.models.models import (
        AuditLog, Notification, DocumentLineItem, WorkflowState,
        ValidationResult, MatchingResult, Exception as Ex, Approval,
        ERPPosting, PaymentSchedule,
    )
    from sqlalchemy import delete as sa_delete

    doc_id = doc.id
    for model in (AuditLog, Notification, DocumentLineItem, WorkflowState,
                  ValidationResult, MatchingResult, Ex, Approval,
                  ERPPosting, PaymentSchedule):
        await db.execute(sa_delete(model).where(model.document_id == doc_id))
    await db.execute(sa_delete(Document).where(Document.id == doc_id))
    await db.commit()
    return {"status": "deleted", "document_id": document_id}


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """Serve the original uploaded file for inline preview/download."""
    import os
    try:
        doc = await resolve_document(db, document_id)
    except HTTPException:
        doc = None
    if not doc or not doc.original_path or not os.path.isfile(doc.original_path):
        raise HTTPException(status_code=404, detail="File not found")
    media = "application/pdf" if doc.file_extension == "pdf" else f"image/{doc.file_extension}"
    return FileResponse(doc.original_path, media_type=media, filename=doc.original_filename)


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    resolved = await resolve_document(db, document_id)
    result = await db.execute(
        select(Document)
        .options(
            selectinload(Document.vendor),
            selectinload(Document.purchase_order),
            selectinload(Document.grn),
            selectinload(Document.line_items),
        )
        .where(Document.id == resolved.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentOut(
        id=str(doc.id),
        document_id=doc.document_id,
        original_filename=doc.original_filename,
        file_extension=doc.file_extension,
        file_size=doc.file_size,
        status=doc.status,
        doc_type=doc.doc_type,
        business_profile=doc.business_profile,
        ai_profile_confidence=doc.ai_profile_confidence,
        ai_profile_reasoning=doc.ai_profile_reasoning,
        vendor_id=str(doc.vendor_id) if doc.vendor_id else None,
        vendor_name=doc.vendor.name if doc.vendor else None,
        po_id=str(doc.po_id) if doc.po_id else None,
        po_number=doc.purchase_order.po_number if doc.purchase_order else None,
        grn_id=str(doc.grn_id) if doc.grn_id else None,
        grn_number=doc.grn.grn_number if doc.grn else None,
        invoice_number=doc.invoice_number,
        invoice_date=doc.invoice_date,
        invoice_amount=doc.invoice_amount,
        tax_amount=doc.tax_amount,
        total_amount=doc.total_amount,
        currency=doc.currency,
        extracted_data=doc.extracted_data,
        ocr_confidence=doc.ocr_confidence,
        ocr_text=doc.ocr_text,
        ingestion_source=doc.ingestion_source,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        processing_started_at=doc.processing_started_at,
        processing_completed_at=doc.processing_completed_at,
        line_items=[],
    )


@router.get("/{document_id}/workflow", response_model=WorkflowStateOut)
async def get_workflow_state(
    document_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    doc = await resolve_document(db, document_id)
    result = await db.execute(
        select(WorkflowState).where(WorkflowState.document_id == doc.id)
    )
    state = result.scalar_one_or_none()
    if not state:
        raise HTTPException(status_code=404, detail="Workflow state not found")

    return WorkflowStateOut(
        id=str(state.id),
        document_id=str(state.document_id),
        current_stage=state.current_stage,
        current_agent=state.current_agent,
        progress_percent=state.progress_percent,
        error_message=state.error_message,
        stage_history=state.stage_history or [],
        retry_count=state.retry_count,
        started_at=state.started_at,
        completed_at=state.completed_at,
        updated_at=state.updated_at,
    )


@router.get("/{document_id}/validation-results")
async def get_validation_results(
    document_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    from app.models.models import ValidationResult
    doc = await resolve_document(db, document_id)
    result = await db.execute(
        select(ValidationResult)
        .where(ValidationResult.document_id == doc.id)
        .order_by(ValidationResult.created_at)
    )
    vrs = result.scalars().all()
    return [
        {
            "id": str(v.id),
            "rule_code": v.rule_code,
            "rule_name": v.rule_name,
            "status": v.status,
            "expected_value": v.expected_value,
            "actual_value": v.actual_value,
            "reason": v.reason,
            "severity": v.severity,
            "agent": v.agent,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in vrs
    ]


@router.get("/{document_id}/matching")
async def get_matching_result(
    document_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    from app.models.models import MatchingResult
    doc = await resolve_document(db, document_id)
    result = await db.execute(
        select(MatchingResult).where(MatchingResult.document_id == doc.id)
    )
    mr = result.scalar_one_or_none()
    if not mr:
        raise HTTPException(status_code=404, detail="Matching result not found")
    return {
        "id": str(mr.id),
        "match_status": mr.match_status,
        "overall_match_score": float(mr.overall_match_score or 0),
        "quantity_match": mr.quantity_match,
        "price_match": mr.price_match,
        "tax_match": mr.tax_match,
        "total_match": mr.total_match,
        "vendor_match": mr.vendor_match,
        "variance_report": mr.variance_report,
        "line_matches": mr.line_matches,
        "tolerance_applied": mr.tolerance_applied,
        "matching_notes": mr.matching_notes,
    }


@router.get("/{document_id}/audit-trail")
async def get_audit_trail(
    document_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    from app.models.models import AuditLog
    doc = await resolve_document(db, document_id)
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.document_id == doc.id)
        .order_by(AuditLog.timestamp)
    )
    logs = result.scalars().all()
    return [
        {
            "id": str(l.id),
            "entity_type": l.entity_type,
            "action": l.action,
            "agent": l.agent,
            "stage": l.stage,
            "before_state": l.before_state,
            "after_state": l.after_state,
            "metadata": l.log_metadata,
            "timestamp": l.timestamp.isoformat() if l.timestamp else None,
        }
        for l in logs
    ]


@router.get("/task/{task_id}/status")
async def get_task_status(task_id: str):
    from app.core.celery_app import celery_app
    try:
        result = celery_app.AsyncResult(task_id)
        status = result.status
        ready  = result.ready()
        return {
            "task_id": task_id,
            "status": status,
            "result": result.result if ready else None,
        }
    except Exception:
        # Redis/backend unavailable — return a safe pending response so the
        # frontend keeps polling rather than crashing.
        return {"task_id": task_id, "status": "PENDING", "result": None}
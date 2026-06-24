from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone

from app.core.database import get_async_session
from app.core.security import get_current_user
from app.models.models import Approval, ApprovalStatus, Document, DocumentStatus, Notification, User
from sqlalchemy.orm import selectinload
from app.schemas.schemas import ApprovalAction, ApprovalOut

router = APIRouter(prefix="/approvals", tags=["Approvals"])


@router.get("/my", response_model=List[ApprovalOut])
async def my_approvals(
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    q = select(Approval).options(selectinload(Approval.document), selectinload(Approval.approver)).where(
        (Approval.approver_id == str(current_user.id)) |
        (Approval.delegate_id == str(current_user.id))
    )
    if status:
        q = q.where(Approval.status == status)
    q = q.order_by(desc(Approval.created_at))
    result = await db.execute(q)
    approvals = result.scalars().all()
    return [_map_approval(a, current_user) for a in approvals]


@router.get("", response_model=List[ApprovalOut])
async def list_approvals(
    status: Optional[str] = Query(None),
    document_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    q = select(Approval).options(selectinload(Approval.document), selectinload(Approval.approver))
    if status:
        q = q.where(Approval.status == status)
    if document_id:
        from app.api.v1.deps import resolve_document
        doc = await resolve_document(db, document_id)
        q = q.where(Approval.document_id == doc.id)
    q = q.order_by(desc(Approval.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    approvals = result.scalars().all()
    return [_map_approval(a, current_user) for a in approvals]


@router.post("/{approval_id}/action", response_model=ApprovalOut)
async def action_approval(
    approval_id: str,
    body: ApprovalAction,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Approval)
        .options(selectinload(Approval.document), selectinload(Approval.approver))
        .where(Approval.id == approval_id)
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if str(approval.approver_id) != str(current_user.id) and str(approval.delegate_id or "") != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized to action this approval")

    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Approval is already {approval.status}")

    if body.action not in ("APPROVE", "REJECT"):
        raise HTTPException(status_code=400, detail="Action must be APPROVE or REJECT")

    approval.status = ApprovalStatus.APPROVED if body.action == "APPROVE" else ApprovalStatus.REJECTED
    approval.action = body.action
    approval.comments = body.comments
    approval.actioned_at = datetime.now(timezone.utc)
    await db.flush()

    doc_result = await db.execute(select(Document).where(Document.id == approval.document_id))
    doc = doc_result.scalar_one_or_none()

    if body.action == "APPROVE":
        # Check if there are more pending approvals
        next_approval_result = await db.execute(
            select(Approval).where(
                Approval.document_id == approval.document_id,
                Approval.approval_level > approval.approval_level,
                Approval.status.in_(["WAITING", ApprovalStatus.PENDING]),
            ).order_by(Approval.approval_level)
        )
        next_approval = next_approval_result.scalars().first()

        if next_approval:
            next_approval.status = ApprovalStatus.PENDING
            # Notify next approver
            notif = Notification(
                user_id=str(next_approval.approver_id),
                document_id=str(approval.document_id),
                notification_type="APPROVAL_REQUIRED",
                title="Approval Required",
                body=f"Level {approval.approval_level} approved. Your approval (level {next_approval.approval_level}) is now required.",
                action_url=f"/approvals/{next_approval.id}",
            )
            db.add(notif)
        else:
            # All levels approved — trigger ERP posting
            if doc:
                doc.status = DocumentStatus.APPROVED
            from app.tasks.pipeline import run_post_approval_pipeline
            run_post_approval_pipeline.delay(str(approval.document_id))
    else:
        # Rejected
        if doc:
            doc.status = DocumentStatus.REJECTED

    await db.flush()
    return _map_approval(approval, current_user)


@router.post("/{approval_id}/delegate")
async def delegate_approval(
    approval_id: str,
    delegate_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Approval).where(Approval.id == approval_id))
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    delegate = await db.get(User, delegate_id)
    if not delegate:
        raise HTTPException(status_code=404, detail="Delegate user not found")

    approval.delegate_id = delegate_id
    approval.status = ApprovalStatus.DELEGATED
    await db.flush()
    return {"message": f"Delegated to {delegate.name}"}


def _map_approval(a: Approval, current_user: User) -> ApprovalOut:
    doc_ref = (a.document.document_id if hasattr(a, "document") and a.document else None) or str(a.document_id)
    return ApprovalOut(
        id=str(a.id),
        document_id=doc_ref,
        approval_level=a.approval_level,
        approver_id=str(a.approver_id),
        approver_name=a.approver.name if hasattr(a, "approver") and a.approver else None,
        delegate_id=str(a.delegate_id) if a.delegate_id else None,
        status=a.status,
        action=a.action,
        comments=a.comments,
        actioned_at=a.actioned_at,
        deadline=a.deadline,
        created_at=a.created_at,
    )
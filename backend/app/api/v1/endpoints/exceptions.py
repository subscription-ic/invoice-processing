from __future__ import annotations

from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.security import get_current_user
from app.models.models import Exception as Ex, ExceptionStatus, User
from app.schemas.schemas import ExceptionAssign, ExceptionOut, ExceptionResolve

router = APIRouter(prefix="/exceptions", tags=["Exceptions"])


@router.get("", response_model=List[ExceptionOut])
async def list_exceptions(
    queue: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    assigned_to_me: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    q = select(Ex)
    if queue:
        q = q.where(Ex.queue == queue)
    if status:
        q = q.where(Ex.status == status)
    if severity:
        q = q.where(Ex.severity == severity)
    if assigned_to_me:
        q = q.where(Ex.assigned_to == str(current_user.id))
    q = q.order_by(desc(Ex.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    exceptions = result.scalars().all()
    return [_map_exception(e) for e in exceptions]


@router.get("/{exception_id}", response_model=ExceptionOut)
async def get_exception(
    exception_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Ex).where(Ex.id == exception_id))
    ex = result.scalar_one_or_none()
    if not ex:
        raise HTTPException(status_code=404, detail="Exception not found")
    return _map_exception(ex)


@router.post("/{exception_id}/resolve", response_model=ExceptionOut)
async def resolve_exception(
    exception_id: str,
    body: ExceptionResolve,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Ex).where(Ex.id == exception_id))
    ex = result.scalar_one_or_none()
    if not ex:
        raise HTTPException(status_code=404, detail="Exception not found")

    ex.status = body.status
    ex.resolution_notes = body.resolution_notes
    ex.resolved_by = str(current_user.id)
    ex.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return _map_exception(ex)


@router.post("/{exception_id}/assign", response_model=ExceptionOut)
async def assign_exception(
    exception_id: str,
    body: ExceptionAssign,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Ex).where(Ex.id == exception_id))
    ex = result.scalar_one_or_none()
    if not ex:
        raise HTTPException(status_code=404, detail="Exception not found")

    ex.assigned_to = body.assigned_to
    ex.status = ExceptionStatus.IN_PROGRESS
    await db.flush()
    return _map_exception(ex)


def _map_exception(e: Ex) -> ExceptionOut:
    return ExceptionOut(
        id=str(e.id),
        document_id=str(e.document_id),
        exception_code=e.exception_code,
        exception_type=e.exception_type,
        severity=e.severity,
        queue=e.queue,
        title=e.title,
        description=e.description,
        agent_raised_by=e.agent_raised_by,
        assigned_to=str(e.assigned_to) if e.assigned_to else None,
        assignee_name=None,
        status=e.status,
        sla_hours=e.sla_hours,
        sla_deadline=e.sla_deadline,
        resolution_notes=e.resolution_notes,
        resolved_at=e.resolved_at,
        escalation_count=e.escalation_count or 0,
        created_at=e.created_at,
    )
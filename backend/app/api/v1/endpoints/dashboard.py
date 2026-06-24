from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal
from typing import Any, Dict, List

from app.core.database import get_async_session
from app.core.security import get_current_user
from app.models.models import (
    Approval, ApprovalStatus, Document, DocumentStatus, Exception as Ex,
    ExceptionStatus, MatchingResult, MatchStatus, User, Vendor
)
from app.schemas.schemas import DashboardStats

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    from datetime import date, datetime, timezone, timedelta

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Total documents
    total_result = await db.execute(select(func.count(Document.id)))
    total_docs = total_result.scalar() or 0

    # Documents today
    today_result = await db.execute(
        select(func.count(Document.id)).where(Document.created_at >= today_start)
    )
    docs_today = today_result.scalar() or 0

    # Pending approvals
    pending_approvals_result = await db.execute(
        select(func.count(Approval.id)).where(Approval.status == ApprovalStatus.PENDING)
    )
    pending_approvals = pending_approvals_result.scalar() or 0

    # Open exceptions
    open_ex_result = await db.execute(
        select(func.count(Ex.id)).where(Ex.status.in_([ExceptionStatus.OPEN, ExceptionStatus.IN_PROGRESS]))
    )
    open_exceptions = open_ex_result.scalar() or 0

    # Matching rate
    total_matched_result = await db.execute(
        select(func.count(MatchingResult.id)).where(
            MatchingResult.match_status.in_([MatchStatus.MATCHED, MatchStatus.TOLERANCE_MATCH])
        )
    )
    total_matching_result = await db.execute(select(func.count(MatchingResult.id)))
    total_matched = total_matched_result.scalar() or 0
    total_matching = total_matching_result.scalar() or 1
    matching_rate = Decimal(str(total_matched / total_matching * 100)).quantize(Decimal("0.01"))

    # Avg processing time
    avg_result = await db.execute(
        select(func.avg(
            func.extract("epoch", Document.processing_completed_at - Document.processing_started_at) / 60
        )).where(
            Document.processing_completed_at.isnot(None),
            Document.processing_started_at.isnot(None),
        )
    )
    avg_processing = avg_result.scalar()

    # Total invoice amount
    amount_result = await db.execute(
        select(func.coalesce(func.sum(Document.total_amount), 0))
    )
    total_amount = amount_result.scalar() or Decimal("0")

    # Documents by status
    status_result = await db.execute(
        select(Document.status, func.count(Document.id)).group_by(Document.status)
    )
    docs_by_status = {row[0]: row[1] for row in status_result.all()}

    # Documents by profile
    profile_result = await db.execute(
        select(Document.business_profile, func.count(Document.id))
        .where(Document.business_profile.isnot(None))
        .group_by(Document.business_profile)
    )
    docs_by_profile = {row[0]: row[1] for row in profile_result.all()}

    # Documents by source
    source_result = await db.execute(
        select(Document.ingestion_source, func.count(Document.id)).group_by(Document.ingestion_source)
    )
    docs_by_source = {row[0]: row[1] for row in source_result.all()}

    # Exceptions by queue
    ex_queue_result = await db.execute(
        select(Ex.queue, func.count(Ex.id))
        .where(Ex.status.in_([ExceptionStatus.OPEN, ExceptionStatus.IN_PROGRESS]))
        .group_by(Ex.queue)
    )
    ex_by_queue = {row[0]: row[1] for row in ex_queue_result.all()}

    # Top vendors by amount — inner join so only vendors with actual invoices appear
    top_vendors_result = await db.execute(
        select(Vendor.name, func.sum(Document.total_amount).label("total"))
        .join(Document, Document.vendor_id == Vendor.id)
        .group_by(Vendor.id, Vendor.name)
        .having(func.sum(Document.total_amount) > 0)
        .order_by(func.sum(Document.total_amount).desc())
        .limit(10)
    )
    top_vendors = [{"vendor": row[0], "amount": float(row[1])} for row in top_vendors_result.all()]

    # Processing trend (last 7 days)
    trend = []
    for days_ago in range(6, -1, -1):
        day_start = today_start - timedelta(days=days_ago)
        day_end = day_start + timedelta(days=1)
        day_result = await db.execute(
            select(func.count(Document.id)).where(
                Document.created_at >= day_start,
                Document.created_at < day_end,
            )
        )
        count = day_result.scalar() or 0
        trend.append({"date": day_start.date().isoformat(), "count": count})

    return DashboardStats(
        total_documents=total_docs,
        documents_today=docs_today,
        pending_approvals=pending_approvals,
        open_exceptions=open_exceptions,
        matching_rate=matching_rate,
        avg_processing_time_minutes=Decimal(str(avg_processing)).quantize(Decimal("0.01")) if avg_processing else None,
        total_invoice_amount=Decimal(str(total_amount)),
        documents_by_status=docs_by_status,
        documents_by_profile=docs_by_profile,
        documents_by_source=docs_by_source,
        exception_by_queue=ex_by_queue,
        top_vendors_by_amount=top_vendors,
        processing_trend=trend,
        approval_sla_stats={"pending": pending_approvals, "open_exceptions": open_exceptions},
    )


@router.get("/notifications")
async def get_notifications(
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    from app.models.models import Notification
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == str(current_user.id))
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    notifs = result.scalars().all()
    return [
        {
            "id": str(n.id), "type": n.notification_type, "title": n.title,
            "body": n.body, "action_url": n.action_url, "is_read": n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notifs
    ]


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    from app.models.models import Notification
    from datetime import datetime, timezone
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == str(current_user.id),
        )
    )
    notif = result.scalar_one_or_none()
    if notif:
        notif.is_read = True
        notif.read_at = datetime.now(timezone.utc)
    return {"status": "ok"}
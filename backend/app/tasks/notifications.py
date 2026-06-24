from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.celery_app import celery_app
from app.core.database import SyncSessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.notifications.send_approval_reminders", queue="default")
def send_approval_reminders() -> None:
    """Send reminders for pending approvals approaching deadline."""
    from app.models.models import Approval, ApprovalStatus, Notification
    from datetime import timedelta

    db = SyncSessionLocal()
    try:
        now = datetime.now(timezone.utc)
        reminder_threshold = now + timedelta(hours=4)

        pending = (
            db.query(Approval)
            .filter(
                Approval.status == ApprovalStatus.PENDING,
                Approval.deadline <= reminder_threshold,
                Approval.deadline > now,
                Approval.reminder_count < 3,
            )
            .all()
        )

        for approval in pending:
            notif = Notification(
                user_id=str(approval.approver_id),
                document_id=approval.document_id,
                notification_type="APPROVAL_REMINDER",
                title="Approval Reminder",
                body=f"Your approval is due soon. Deadline: {approval.deadline.strftime('%d %b %Y %H:%M')}",
                action_url=f"/approvals/{approval.id}",
            )
            db.add(notif)
            approval.reminder_count = (approval.reminder_count or 0) + 1
            approval.last_reminder_at = now

        db.commit()
        logger.info(f"Sent {len(pending)} approval reminders")
    finally:
        db.close()
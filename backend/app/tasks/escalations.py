from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.celery_app import celery_app
from app.core.database import SyncSessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.escalations.check_sla_escalations", queue="default")
def check_sla_escalations() -> None:
    """Escalate exceptions that have breached SLA."""
    from app.models.models import Exception as Ex, ExceptionStatus, Notification

    db = SyncSessionLocal()
    try:
        now = datetime.now(timezone.utc)

        breached = (
            db.query(Ex)
            .filter(
                Ex.status.in_([ExceptionStatus.OPEN, ExceptionStatus.IN_PROGRESS]),
                Ex.sla_deadline <= now,
                Ex.escalation_count < 3,
            )
            .all()
        )

        for ex in breached:
            ex.escalation_count = (ex.escalation_count or 0) + 1
            ex.status = ExceptionStatus.ESCALATED
            ex.escalated_at = now

            notif = Notification(
                user_id=str(ex.assigned_to) if ex.assigned_to else None,
                document_id=ex.document_id,
                notification_type="SLA_BREACHED",
                title=f"SLA Breached: {ex.title}",
                body=f"Exception has breached SLA. Escalation count: {ex.escalation_count}",
                action_url=f"/exceptions/{ex.id}",
            )
            if notif.user_id:
                db.add(notif)

        db.commit()
        logger.info(f"Escalated {len(breached)} exceptions")
    finally:
        db.close()
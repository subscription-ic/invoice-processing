from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "ap_platform",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.pipeline",
        "app.tasks.notifications",
        "app.tasks.escalations",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.tasks.pipeline.*": {"queue": "pipeline"},
        "app.tasks.notifications.*": {"queue": "default"},
        "app.tasks.escalations.*": {"queue": "default"},
    },
    beat_schedule={
        "check-sla-escalations": {
            "task": "app.tasks.escalations.check_sla_escalations",
            "schedule": crontab(minute="*/15"),
        },
        "send-approval-reminders": {
            "task": "app.tasks.notifications.send_approval_reminders",
            "schedule": crontab(hour="*/2"),
        },
        "update-payment-schedules": {
            "task": "app.tasks.pipeline.update_payment_statuses",
            "schedule": crontab(hour="8", minute="0"),
        },
    },
)
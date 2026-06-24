"""
Notification Service — Phase 9.

Dispatches notifications via multiple channels (email, webhook, in-app)
and records every attempt in the NotificationLog table.

Usage:
    from app.services.notification_service import NotificationService

    svc = NotificationService(db=db_session)
    await svc.dispatch(
        event_type="INVOICE_APPROVED",
        channel="email",
        recipient="approver@company.com",
        template_id="invoice_approved",
        payload={"invoice_number": "INV-001", "amount": 5000},
        document_id="...",
        tenant_id="default",
    )

Security rules enforced:
  - Never log PII from payload — only log template_id and document_id hash.
  - SMTP credentials must come from environment, never hardcoded.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import NotificationLog

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Channel constants
# ---------------------------------------------------------------------------
CHANNEL_EMAIL = "email"
CHANNEL_WEBHOOK = "webhook"
CHANNEL_IN_APP = "in_app"

STATUS_PENDING = "PENDING"
STATUS_SENT = "SENT"
STATUS_FAILED = "FAILED"

SUPPORTED_CHANNELS = {CHANNEL_EMAIL, CHANNEL_WEBHOOK, CHANNEL_IN_APP}


class NotificationService:
    """
    Dispatches notifications and persists delivery attempts to NotificationLog.
    One instance per request (takes the DB session from FastAPI DI).
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Public dispatch entry-point
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        event_type: str,
        channel: str,
        recipient: str,
        template_id: str,
        payload: Dict[str, Any],
        *,
        document_id: Optional[str] = None,
        tenant_id: str = "default",
    ) -> NotificationLog:
        """
        Dispatch a notification on the requested channel.
        Always writes a NotificationLog row regardless of outcome.
        """
        if channel not in SUPPORTED_CHANNELS:
            raise ValueError(f"Unsupported notification channel: {channel}")

        log_entry = NotificationLog(
            tenant_id=tenant_id,
            document_id=document_id,
            event_type=event_type,
            channel=channel,
            recipient=self._hash_recipient(recipient),
            template_id=template_id,
            status=STATUS_PENDING,
        )
        self._db.add(log_entry)
        await self._db.flush()

        try:
            if channel == CHANNEL_EMAIL:
                await self._send_email(recipient, template_id, payload, event_type)
            elif channel == CHANNEL_WEBHOOK:
                await self._send_webhook(recipient, template_id, payload, event_type, tenant_id)
            elif channel == CHANNEL_IN_APP:
                await self._send_in_app(recipient, template_id, payload, event_type, tenant_id, document_id)

            log_entry.status = STATUS_SENT
        except Exception as exc:
            log_entry.status = STATUS_FAILED
            log_entry.error_message = str(exc)[:500]
            # Log template_id + document_id hash only (no PII, no payload content)
            doc_hash = hashlib.sha256((document_id or "").encode()).hexdigest()[:12]
            logger.warning(
                "Notification dispatch failed — template=%s doc_ref=%s channel=%s error=%s",
                template_id, doc_hash, channel, type(exc).__name__,
            )

        await self._db.commit()
        return log_entry

    # ------------------------------------------------------------------
    # Email
    # ------------------------------------------------------------------

    async def _send_email(
        self,
        to_address: str,
        template_id: str,
        payload: Dict[str, Any],
        event_type: str,
    ) -> None:
        """Send email via SMTP (TLS). Credentials read from environment."""
        smtp_host = os.getenv("SMTP_HOST", "")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_pass = os.getenv("SMTP_PASSWORD", "")
        from_addr = os.getenv("SMTP_FROM", smtp_user or "noreply@example.com")

        if not smtp_host:
            raise RuntimeError("SMTP_HOST is not configured — email dispatch unavailable")

        subject, body_text, body_html = _render_template(template_id, payload, event_type)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_address
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.ehlo()
            server.starttls(context=context)
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, [to_address], msg.as_string())

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------

    async def _send_webhook(
        self,
        url: str,
        template_id: str,
        payload: Dict[str, Any],
        event_type: str,
        tenant_id: str,
    ) -> None:
        """POST event data to a webhook URL using httpx with a 10-second timeout."""
        webhook_secret = os.getenv("WEBHOOK_SECRET", "")
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-Event-Type": event_type,
            "X-Tenant-ID": tenant_id,
            "X-Template-ID": template_id,
        }
        if webhook_secret:
            import hmac
            body = json.dumps({"event": event_type, "template": template_id, "data": payload})
            sig = hmac.new(webhook_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
            headers["X-Signature-256"] = f"sha256={sig}"
        else:
            body = json.dumps({"event": event_type, "template": template_id, "data": payload})

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, content=body, headers=headers)
            resp.raise_for_status()

    # ------------------------------------------------------------------
    # In-App
    # ------------------------------------------------------------------

    async def _send_in_app(
        self,
        user_id: str,
        template_id: str,
        payload: Dict[str, Any],
        event_type: str,
        tenant_id: str,
        document_id: Optional[str],
    ) -> None:
        """Write to the Notification table (existing ORM model) for in-app display."""
        from app.models.models import Notification
        subject, body_text, _ = _render_template(template_id, payload, event_type)
        notif = Notification(
            user_id=user_id,
            notification_type=event_type,
            title=subject,
            body=body_text,
            document_id=document_id,
            is_read=False,
        )
        self._db.add(notif)
        await self._db.flush()

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_recipient(recipient: str) -> str:
        """Store only a SHA-256 hash prefix of the recipient address — never log PII."""
        return "h:" + hashlib.sha256(recipient.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Template rendering (minimal — replace with Jinja2 SandboxedEnvironment)
# ---------------------------------------------------------------------------

_TEMPLATES: Dict[str, Dict[str, str]] = {
    "invoice_approved": {
        "subject": "Invoice Approved — {invoice_number}",
        "text": "Your invoice {invoice_number} for amount {amount} has been approved.",
        "html": "<p>Your invoice <b>{invoice_number}</b> for amount <b>{amount}</b> has been <span style='color:green'>approved</span>.</p>",
    },
    "invoice_rejected": {
        "subject": "Invoice Requires Attention — {invoice_number}",
        "text": "Invoice {invoice_number} was rejected. Reason: {reason}.",
        "html": "<p>Invoice <b>{invoice_number}</b> was <span style='color:red'>rejected</span>. Reason: {reason}.</p>",
    },
    "exception_raised": {
        "subject": "Exception Raised on Invoice {invoice_number}",
        "text": "An exception ({exception_code}) has been raised for invoice {invoice_number}.",
        "html": "<p>Exception <b>{exception_code}</b> raised for invoice <b>{invoice_number}</b>.</p>",
    },
    "approval_required": {
        "subject": "Approval Required — Invoice {invoice_number}",
        "text": "Invoice {invoice_number} for {amount} requires your approval.",
        "html": "<p>Invoice <b>{invoice_number}</b> for <b>{amount}</b> requires your approval.</p>",
    },
    "payment_scheduled": {
        "subject": "Payment Scheduled — Invoice {invoice_number}",
        "text": "Payment for invoice {invoice_number} has been scheduled for {payment_date}.",
        "html": "<p>Payment for invoice <b>{invoice_number}</b> has been scheduled for <b>{payment_date}</b>.</p>",
    },
}

_FALLBACK_TEMPLATE = {
    "subject": "AP System Notification — {event_type}",
    "text": "Event: {event_type}",
    "html": "<p>Event: <b>{event_type}</b></p>",
}


def _render_template(
    template_id: str, payload: Dict[str, Any], event_type: str
) -> tuple[str, str, str]:
    """Render a notification template. Uses safe .format_map() — no exec."""
    tmpl = _TEMPLATES.get(template_id, _FALLBACK_TEMPLATE)
    ctx = {**payload, "event_type": event_type}
    try:
        subject = tmpl["subject"].format_map(ctx)
        text = tmpl["text"].format_map(ctx)
        html = tmpl["html"].format_map(ctx)
    except (KeyError, IndexError):
        subject = f"AP Notification — {event_type}"
        text = f"Event: {event_type}"
        html = f"<p>Event: <b>{event_type}</b></p>"
    return subject, text, html


def _build_message(template_id: str, payload: Dict[str, Any], event_type: str) -> str:
    _, text, _ = _render_template(template_id, payload, event_type)
    return text

"""
Unit tests for Phase 9 NotificationService.

These tests cover pure-Python functions (template rendering, PII hashing)
and do NOT require a database connection.
"""
from __future__ import annotations

import hashlib

import pytest


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

class TestTemplateRendering:

    def test_known_template_renders_subject(self):
        from app.services.notification_service import _render_template
        subject, text, html = _render_template(
            "invoice_approved",
            {"invoice_number": "INV-001", "amount": "₹5,000"},
            "INVOICE_APPROVED",
        )
        assert "INV-001" in subject
        assert "INV-001" in text
        assert "INV-001" in html

    def test_rejection_template(self):
        from app.services.notification_service import _render_template
        subject, text, html = _render_template(
            "invoice_rejected",
            {"invoice_number": "INV-002", "reason": "Amount mismatch"},
            "INVOICE_REJECTED",
        )
        assert "INV-002" in text
        assert "Amount mismatch" in text

    def test_unknown_template_fallback(self):
        from app.services.notification_service import _render_template
        subject, text, html = _render_template(
            "nonexistent_template",
            {},
            "CUSTOM_EVENT",
        )
        assert "CUSTOM_EVENT" in subject or "CUSTOM_EVENT" in text

    def test_missing_placeholder_does_not_raise(self):
        from app.services.notification_service import _render_template
        # Provide empty payload — missing keys should fall back gracefully
        subject, text, html = _render_template("invoice_approved", {}, "TEST")
        assert isinstance(subject, str)
        assert isinstance(text, str)

    def test_payment_scheduled_template(self):
        from app.services.notification_service import _render_template
        subject, text, html = _render_template(
            "payment_scheduled",
            {"invoice_number": "INV-003", "payment_date": "2025-02-28"},
            "PAYMENT_SCHEDULED",
        )
        assert "INV-003" in text
        assert "2025-02-28" in text


# ---------------------------------------------------------------------------
# PII hashing
# ---------------------------------------------------------------------------

class TestPIIHashing:

    def test_recipient_is_hashed(self):
        from app.services.notification_service import NotificationService
        hashed = NotificationService._hash_recipient("approver@company.com")
        assert hashed.startswith("h:")
        assert "approver@company.com" not in hashed

    def test_hash_is_deterministic(self):
        from app.services.notification_service import NotificationService
        h1 = NotificationService._hash_recipient("user@example.com")
        h2 = NotificationService._hash_recipient("user@example.com")
        assert h1 == h2

    def test_different_recipients_different_hash(self):
        from app.services.notification_service import NotificationService
        h1 = NotificationService._hash_recipient("alice@example.com")
        h2 = NotificationService._hash_recipient("bob@example.com")
        assert h1 != h2

    def test_hash_length_is_short(self):
        from app.services.notification_service import NotificationService
        hashed = NotificationService._hash_recipient("user@example.com")
        # Should not be full 64-char SHA-256 — truncated for storage efficiency
        assert len(hashed) <= 20


# ---------------------------------------------------------------------------
# Channel constants
# ---------------------------------------------------------------------------

class TestChannelConstants:

    def test_supported_channels_defined(self):
        from app.services.notification_service import SUPPORTED_CHANNELS
        assert "email" in SUPPORTED_CHANNELS
        assert "webhook" in SUPPORTED_CHANNELS
        assert "in_app" in SUPPORTED_CHANNELS

    def test_status_constants_defined(self):
        from app.services.notification_service import STATUS_SENT, STATUS_FAILED, STATUS_PENDING
        assert STATUS_PENDING == "PENDING"
        assert STATUS_SENT == "SENT"
        assert STATUS_FAILED == "FAILED"

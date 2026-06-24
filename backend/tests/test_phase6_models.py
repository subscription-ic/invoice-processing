"""
Tests for Phase 6 ORM model additions.

These tests verify model structure (class attributes, table names, constraints)
without requiring a live database connection.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# New ORM tables exist and have expected columns
# ---------------------------------------------------------------------------

class TestPhase6NewTables:

    def test_workflow_state_archive_columns(self):
        from app.models.models import WorkflowStateArchive
        assert WorkflowStateArchive.__tablename__ == "workflow_state_archive"
        cols = {c.key for c in WorkflowStateArchive.__table__.columns}
        assert {"id", "document_id", "tenant_id", "workflow_status", "state_json", "archived_at"} <= cols

    def test_workflow_timeline_columns(self):
        from app.models.models import WorkflowTimeline
        assert WorkflowTimeline.__tablename__ == "workflow_timelines"
        cols = {c.key for c in WorkflowTimeline.__table__.columns}
        assert {"id", "document_id", "tenant_id", "node_name", "event_type", "occurred_at"} <= cols

    def test_notification_log_columns(self):
        from app.models.models import NotificationLog
        assert NotificationLog.__tablename__ == "notification_logs"
        cols = {c.key for c in NotificationLog.__table__.columns}
        assert {"id", "document_id", "tenant_id", "event_type", "channel", "status"} <= cols

    def test_retry_log_columns(self):
        from app.models.models import RetryLog
        assert RetryLog.__tablename__ == "retry_logs"
        cols = {c.key for c in RetryLog.__table__.columns}
        assert {"id", "document_id", "tenant_id", "failed_agent", "attempt_number"} <= cols

    def test_exception_resolution_history_columns(self):
        from app.models.models import ExceptionResolutionHistory
        assert ExceptionResolutionHistory.__tablename__ == "exception_resolution_history"
        cols = {c.key for c in ExceptionResolutionHistory.__table__.columns}
        assert {"id", "exception_id", "document_id", "resolution_type", "resolved_at"} <= cols

    def test_feature_flag_columns(self):
        from app.models.models import FeatureFlag
        assert FeatureFlag.__tablename__ == "feature_flags"
        cols = {c.key for c in FeatureFlag.__table__.columns}
        assert {"id", "tenant_id", "flag_name", "is_enabled"} <= cols

    def test_prompt_version_columns(self):
        from app.models.models import PromptVersion
        assert PromptVersion.__tablename__ == "prompt_versions"
        cols = {c.key for c in PromptVersion.__table__.columns}
        assert {"id", "tenant_id", "prompt_name", "version", "content", "is_active"} <= cols

    def test_token_usage_columns(self):
        from app.models.models import TokenUsage
        assert TokenUsage.__tablename__ == "token_usage"
        cols = {c.key for c in TokenUsage.__table__.columns}
        assert {"id", "tenant_id", "document_id", "agent_name", "total_tokens"} <= cols


# ---------------------------------------------------------------------------
# Unique constraints
# ---------------------------------------------------------------------------

class TestPhase6UniqueConstraints:

    def test_feature_flag_unique_constraint(self):
        from app.models.models import FeatureFlag
        from sqlalchemy import UniqueConstraint
        table_args = FeatureFlag.__table_args__ if hasattr(FeatureFlag, "__table_args__") else ()
        constraint_names = {
            c.name for c in table_args
            if isinstance(c, UniqueConstraint)
        }
        assert "uq_feature_flag_tenant_name" in constraint_names

    def test_prompt_version_unique_constraint(self):
        from app.models.models import PromptVersion
        from sqlalchemy import UniqueConstraint
        table_args = PromptVersion.__table_args__ if hasattr(PromptVersion, "__table_args__") else ()
        constraint_names = {
            c.name for c in table_args
            if isinstance(c, UniqueConstraint)
        }
        assert "uq_prompt_version" in constraint_names


# ---------------------------------------------------------------------------
# Existing table column additions (Phase 6)
# ---------------------------------------------------------------------------

class TestPhase6ExistingTableAdditions:

    def test_document_has_tenant_id(self):
        from app.models.models import Document
        cols = {c.key for c in Document.__table__.columns}
        assert "tenant_id" in cols
        assert "overall_confidence_score" in cols
        assert "processing_graph" in cols

    def test_vendor_has_tds_category(self):
        from app.models.models import Vendor
        cols = {c.key for c in Vendor.__table__.columns}
        assert "tds_category" in cols
        assert "payment_method" in cols

    def test_approval_has_authority_amount(self):
        from app.models.models import Approval
        cols = {c.key for c in Approval.__table__.columns}
        assert "authority_amount" in cols

    def test_audit_log_has_event_chain_hash(self):
        from app.models.models import AuditLog
        cols = {c.key for c in AuditLog.__table__.columns}
        assert "event_chain_hash" in cols
        assert "workflow_status" in cols


# ---------------------------------------------------------------------------
# New DocumentStatus constants
# ---------------------------------------------------------------------------

class TestPhase6DocumentStatuses:

    def test_new_statuses_defined(self):
        from app.models.models import DocumentStatus
        assert hasattr(DocumentStatus, "AWAITING_APPROVAL")
        assert hasattr(DocumentStatus, "UNDER_REVIEW")
        assert hasattr(DocumentStatus, "PAYMENT_SCHEDULED")
        assert hasattr(DocumentStatus, "PROFILED")
        assert hasattr(DocumentStatus, "EXCEPTION_RESOLVED")

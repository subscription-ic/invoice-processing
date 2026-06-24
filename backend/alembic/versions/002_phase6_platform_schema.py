"""Phase 6 — enterprise platform schema additions

Adds new columns to existing tables and creates 8 new platform tables.
langgraph_checkpoints is managed by PostgresSaver.setup() — NOT included here.

Revision ID: 002_phase6
Revises: 001_initial
Create Date: 2026-06-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_phase6"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column}).fetchone()
    return row is not None


def _idx_exists(conn, index: str) -> bool:
    row = conn.execute(sa.text(
        "SELECT 1 FROM pg_indexes WHERE indexname = :i"
    ), {"i": index}).fetchone()
    return row is not None


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
    ), {"t": table}).fetchone()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Existing table: documents ────────────────────────────────────────────
    if not _col_exists(conn, "documents", "tenant_id"):
        op.add_column("documents",
            sa.Column("tenant_id", sa.String(100), nullable=False, server_default="default"))
    if not _col_exists(conn, "documents", "workflow_state_id"):
        op.add_column("documents",
            sa.Column("workflow_state_id", postgresql.UUID(as_uuid=False), nullable=True))
    if not _col_exists(conn, "documents", "overall_confidence_score"):
        op.add_column("documents",
            sa.Column("overall_confidence_score", sa.Numeric(5, 4), nullable=True))
    if not _col_exists(conn, "documents", "processing_graph"):
        op.add_column("documents",
            sa.Column("processing_graph", sa.String(50), nullable=True))
    if not _idx_exists(conn, "ix_documents_tenant_id"):
        op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])

    # ── Existing table: vendors ──────────────────────────────────────────────
    if not _col_exists(conn, "vendors", "tds_category"):
        op.add_column("vendors",
            sa.Column("tds_category", sa.String(50), nullable=True))
    if not _col_exists(conn, "vendors", "payment_method"):
        op.add_column("vendors",
            sa.Column("payment_method", sa.String(20), nullable=True))
    if not _col_exists(conn, "vendors", "bank_account_changed_at"):
        op.add_column("vendors",
            sa.Column("bank_account_changed_at", sa.DateTime(timezone=True), nullable=True))

    # ── Existing table: exceptions ───────────────────────────────────────────
    if not _col_exists(conn, "exceptions", "resolution_type"):
        op.add_column("exceptions",
            sa.Column("resolution_type", sa.String(50), nullable=True))

    # ── Existing table: approvals ────────────────────────────────────────────
    if not _col_exists(conn, "approvals", "authority_amount"):
        op.add_column("approvals",
            sa.Column("authority_amount", sa.Numeric(18, 2), nullable=True))

    # ── Existing table: audit_logs ───────────────────────────────────────────
    if not _col_exists(conn, "audit_logs", "event_chain_hash"):
        op.add_column("audit_logs",
            sa.Column("event_chain_hash", sa.String(64), nullable=True))
    if not _col_exists(conn, "audit_logs", "workflow_status"):
        op.add_column("audit_logs",
            sa.Column("workflow_status", sa.String(50), nullable=True))

    # ── New tables (skipped if 001_initial's create_all already made them) ───
    if not _table_exists(conn, "workflow_state_archive"):
        op.create_table(
            "workflow_state_archive",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column("document_id", postgresql.UUID(as_uuid=False),
                      sa.ForeignKey("documents.id"), nullable=False),
            sa.Column("tenant_id", sa.String(100), nullable=False, server_default="default"),
            sa.Column("workflow_status", sa.String(50), nullable=False),
            sa.Column("processing_graph", sa.String(50), nullable=True),
            sa.Column("state_json", sa.Text, nullable=False),
            sa.Column("archived_at", sa.DateTime(timezone=True),
                      server_default=sa.text("NOW()"), nullable=False),
        )
    if not _idx_exists(conn, "ix_workflow_state_archive_doc"):
        op.create_index("ix_workflow_state_archive_doc", "workflow_state_archive", ["document_id"])

    if not _table_exists(conn, "workflow_timelines"):
        op.create_table(
            "workflow_timelines",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column("document_id", postgresql.UUID(as_uuid=False),
                      sa.ForeignKey("documents.id"), nullable=False),
            sa.Column("tenant_id", sa.String(100), nullable=False, server_default="default"),
            sa.Column("node_name", sa.String(100), nullable=False),
            sa.Column("agent_name", sa.String(100), nullable=True),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("status", sa.String(50), nullable=True),
            sa.Column("duration_ms", sa.Integer, nullable=True),
            sa.Column("payload", sa.JSON, nullable=True),
            sa.Column("occurred_at", sa.DateTime(timezone=True),
                      server_default=sa.text("NOW()"), nullable=False),
        )
    if not _idx_exists(conn, "ix_workflow_timelines_doc_time"):
        op.create_index("ix_workflow_timelines_doc_time",
                        "workflow_timelines", ["document_id", "occurred_at"])

    if not _table_exists(conn, "notification_logs"):
        op.create_table(
            "notification_logs",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column("document_id", postgresql.UUID(as_uuid=False),
                      sa.ForeignKey("documents.id"), nullable=True),
            sa.Column("tenant_id", sa.String(100), nullable=False, server_default="default"),
            sa.Column("event_type", sa.String(100), nullable=False),
            sa.Column("channel", sa.String(50), nullable=False),
            sa.Column("recipient", sa.String(255), nullable=True),
            sa.Column("template_id", sa.String(100), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True),
                      server_default=sa.text("NOW()"), nullable=False),
        )
    if not _idx_exists(conn, "ix_notification_logs_doc"):
        op.create_index("ix_notification_logs_doc", "notification_logs", ["document_id"])
    if not _idx_exists(conn, "ix_notification_logs_status"):
        op.create_index("ix_notification_logs_status", "notification_logs", ["status"])

    if not _table_exists(conn, "retry_logs"):
        op.create_table(
            "retry_logs",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column("document_id", postgresql.UUID(as_uuid=False),
                      sa.ForeignKey("documents.id"), nullable=True),
            sa.Column("tenant_id", sa.String(100), nullable=False, server_default="default"),
            sa.Column("failed_agent", sa.String(100), nullable=False),
            sa.Column("attempt_number", sa.Integer, nullable=False, server_default="1"),
            sa.Column("backoff_seconds", sa.Integer, nullable=True),
            sa.Column("error_code", sa.String(100), nullable=True),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("escalated", sa.Boolean, nullable=True, server_default="false"),
            sa.Column("attempted_at", sa.DateTime(timezone=True),
                      server_default=sa.text("NOW()"), nullable=False),
        )
    if not _idx_exists(conn, "ix_retry_logs_doc"):
        op.create_index("ix_retry_logs_doc", "retry_logs", ["document_id"])

    if not _table_exists(conn, "exception_resolution_history"):
        op.create_table(
            "exception_resolution_history",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column("exception_id", postgresql.UUID(as_uuid=False),
                      sa.ForeignKey("exceptions.id"), nullable=False),
            sa.Column("document_id", postgresql.UUID(as_uuid=False),
                      sa.ForeignKey("documents.id"), nullable=False),
            sa.Column("tenant_id", sa.String(100), nullable=False, server_default="default"),
            sa.Column("resolution_type", sa.String(50), nullable=False),
            sa.Column("resolution_notes", sa.Text, nullable=True),
            sa.Column("resolved_by", postgresql.UUID(as_uuid=False),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("corrected_fields", sa.JSON, nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True),
                      server_default=sa.text("NOW()"), nullable=False),
        )
    if not _idx_exists(conn, "ix_exc_resolution_history_exc"):
        op.create_index("ix_exc_resolution_history_exc",
                        "exception_resolution_history", ["exception_id"])
    if not _idx_exists(conn, "ix_exc_resolution_history_doc"):
        op.create_index("ix_exc_resolution_history_doc",
                        "exception_resolution_history", ["document_id"])

    if not _table_exists(conn, "feature_flags"):
        op.create_table(
            "feature_flags",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column("tenant_id", sa.String(100), nullable=False, server_default="default"),
            sa.Column("flag_name", sa.String(100), nullable=False),
            sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("NOW()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("tenant_id", "flag_name", name="uq_feature_flag_tenant_name"),
        )
    if not _idx_exists(conn, "ix_feature_flags_tenant"):
        op.create_index("ix_feature_flags_tenant", "feature_flags", ["tenant_id"])

    if not _table_exists(conn, "prompt_versions"):
        op.create_table(
            "prompt_versions",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column("tenant_id", sa.String(100), nullable=False, server_default="default"),
            sa.Column("prompt_name", sa.String(100), nullable=False),
            sa.Column("version", sa.String(20), nullable=False),
            sa.Column("content", sa.Text, nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("created_by", postgresql.UUID(as_uuid=False),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("NOW()"), nullable=False),
            sa.UniqueConstraint("tenant_id", "prompt_name", "version", name="uq_prompt_version"),
        )
    if not _idx_exists(conn, "ix_prompt_versions_tenant_name"):
        op.create_index("ix_prompt_versions_tenant_name",
                        "prompt_versions", ["tenant_id", "prompt_name"])

    if not _table_exists(conn, "token_usage"):
        op.create_table(
            "token_usage",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column("tenant_id", sa.String(100), nullable=False, server_default="default"),
            sa.Column("document_id", postgresql.UUID(as_uuid=False),
                      sa.ForeignKey("documents.id"), nullable=True),
            sa.Column("agent_name", sa.String(100), nullable=True),
            sa.Column("model", sa.String(100), nullable=True),
            sa.Column("prompt_tokens", sa.Integer, nullable=True, server_default="0"),
            sa.Column("completion_tokens", sa.Integer, nullable=True, server_default="0"),
            sa.Column("total_tokens", sa.Integer, nullable=True, server_default="0"),
            sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True, server_default="0"),
            sa.Column("recorded_at", sa.DateTime(timezone=True),
                      server_default=sa.text("NOW()"), nullable=False),
        )
    if not _idx_exists(conn, "ix_token_usage_tenant"):
        op.create_index("ix_token_usage_tenant", "token_usage", ["tenant_id"])
    if not _idx_exists(conn, "ix_token_usage_doc"):
        op.create_index("ix_token_usage_doc", "token_usage", ["document_id"])


def downgrade() -> None:
    # Drop new tables (reverse order of creation to respect FK constraints)
    op.drop_table("token_usage")
    op.drop_table("prompt_versions")
    op.drop_table("feature_flags")
    op.drop_table("exception_resolution_history")
    op.drop_table("retry_logs")
    op.drop_table("notification_logs")
    op.drop_table("workflow_timelines")
    op.drop_table("workflow_state_archive")

    # Remove new columns from existing tables
    op.drop_column("audit_logs", "workflow_status")
    op.drop_column("audit_logs", "event_chain_hash")
    op.drop_column("approvals", "authority_amount")
    op.drop_column("exceptions", "resolution_type")
    op.drop_column("vendors", "bank_account_changed_at")
    op.drop_column("vendors", "payment_method")
    op.drop_column("vendors", "tds_category")
    op.drop_index("ix_documents_tenant_id", table_name="documents")
    op.drop_column("documents", "processing_graph")
    op.drop_column("documents", "overall_confidence_score")
    op.drop_column("documents", "workflow_state_id")
    op.drop_column("documents", "tenant_id")

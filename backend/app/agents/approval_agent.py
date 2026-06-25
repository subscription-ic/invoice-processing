from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.agents.base import AgentState, BaseAgent
from app.models.models import (
    Approval, ApprovalRule, ApprovalStatus, Document, DocumentStatus,
    MatchingResult, Notification, ProcessingStage, User, ValidationResult,
)
from app.tools.audit_tool import log_audit, update_workflow_stage

AUTO_APPROVE_THRESHOLD = Decimal("25000")


class ApprovalAgent(BaseAgent):
    """
    Agent 10: APPROVAL ROUTING
    DB-driven approval matrix.
    Creates multi-level sequential approvals.
    Handles delegation and escalation.
    """

    name = "APPROVAL_AGENT"
    progress_on_entry = 85
    progress_on_exit = 90

    def _execute(self, state: AgentState) -> AgentState:
        document_id: str = state["document_id"]
        doc = self.db.query(Document).filter(Document.id == document_id).first()

        # Auto-approve low-value invoices with no validation failures
        amount = Decimal(str(doc.total_amount or 0))
        if 0 < amount < AUTO_APPROVE_THRESHOLD:
            fail_count = (
                self.db.query(ValidationResult)
                .filter(ValidationResult.document_id == document_id, ValidationResult.status == "FAIL")
                .count()
            )
            mr = self.db.query(MatchingResult).filter(MatchingResult.document_id == document_id).first()
            matching_ok = (not mr) or mr.match_status in ("MATCHED", "TOLERANCE_MATCH", "NOT_APPLICABLE")
            if fail_count == 0 and matching_ok:
                return self._auto_approve_low_value(state, doc, document_id, amount)

        # Find matching approval rule
        rule = self._find_approval_rule(doc)
        if not rule:
            return self._auto_approve_no_rule(state, doc, document_id)

        # Build approval chain from matrix
        approval_matrix = rule.approval_matrix or []
        now = datetime.now(timezone.utc)
        approvals_created = []

        for level_config in sorted(approval_matrix, key=lambda x: x.get("level", 1)):
            level = level_config.get("level", 1)
            approver_user = self._resolve_approver(level_config, doc)

            if not approver_user:
                self.logger.warning(f"No approver found for level {level} — skipping")
                continue

            escalation_hours = level_config.get("escalation_hours", 24)
            deadline = now + timedelta(hours=escalation_hours)

            approval = Approval(
                document_id=document_id,
                approval_rule_id=rule.id,
                approval_level=level,
                approver_id=approver_user.id,
                status=ApprovalStatus.PENDING if level == 1 else "WAITING",
                deadline=deadline,
            )
            self.db.add(approval)
            approvals_created.append(approval)

        self.db.flush()

        # If no approver users could be resolved (e.g. roles not staffed),
        # auto-approve so the document doesn't get stuck with nothing to action.
        if not approvals_created:
            log_audit(
                self.db,
                document_id=document_id,
                entity_type="APPROVAL",
                action="AUTO_APPROVED_NO_APPROVER",
                agent=self.name,
                log_metadata={"reason": f"Rule '{rule.name}' matched but no approver users available — auto-approved"},
                stage=ProcessingStage.APPROVAL,
            )
            doc.status = DocumentStatus.APPROVED
            self.db.flush()
            update_workflow_stage(
                self.db, document_id=document_id,
                stage=ProcessingStage.ERP_POSTING,
                agent=self.name, progress_percent=90,
            )
            state.set_status("APPROVED")
            state.set_next_agent("ERP_POSTING_AGENT")
            return state

        # Notify first-level approver
        first = approvals_created[0]
        first.status = ApprovalStatus.PENDING
        self._notify_approver(first, doc)

        doc.status = DocumentStatus.PENDING_APPROVAL
        self.db.flush()

        log_audit(
            self.db,
            document_id=document_id,
            entity_type="APPROVAL",
            entity_id=document_id,
            action="APPROVAL_CHAIN_CREATED",
            agent=self.name,
            after_state={
                "levels": len(approvals_created),
                "rule": rule.name,
                "first_approver": str(approvals_created[0].approver_id),
            },
            stage=ProcessingStage.APPROVAL,
        )

        update_workflow_stage(
            self.db, document_id=document_id,
            stage=ProcessingStage.APPROVAL,
            agent=self.name, progress_percent=90,
        )

        state["approval_levels"] = len(approvals_created)
        state["approval_rule"] = rule.name
        state.set_status("PENDING_APPROVAL")
        state.set_next_agent(None)  # Approval is human-driven
        return state

    def _find_approval_rule(self, doc: Document) -> Optional[ApprovalRule]:
        amount = Decimal(str(doc.total_amount or 0))
        query = (
            self.db.query(ApprovalRule)
            .filter(
                ApprovalRule.is_active == True,
                (ApprovalRule.business_profile == doc.business_profile) |
                (ApprovalRule.business_profile == None),
                ApprovalRule.amount_min <= amount,
            )
            .filter(
                (ApprovalRule.amount_max == None) | (ApprovalRule.amount_max >= amount)
            )
            .order_by(ApprovalRule.priority.desc())
        )
        return query.first()

    def _resolve_approver(self, level_config: Dict, doc: Document) -> Optional[User]:
        # All approvals are routed to the System Admin (single professional approver).
        admin = (
            self.db.query(User)
            .filter(User.email == "admin@company.com", User.is_active == True)
            .first()
        )
        if admin:
            return admin

        # Fallback to matrix-based resolution if the admin user is unavailable.
        user_id = level_config.get("user_id")
        role = level_config.get("role")
        if user_id:
            return self.db.query(User).filter(User.id == user_id, User.is_active == True).first()
        if role:
            return self.db.query(User).filter(User.role == role, User.is_active == True).first()
        return None

    def _notify_approver(self, approval: Approval, doc: Document) -> None:
        notif = Notification(
            user_id=str(approval.approver_id),
            document_id=doc.id,
            notification_type="APPROVAL_REQUIRED",
            title=f"Approval Required: {doc.document_id}",
            body=f"Invoice {doc.invoice_number or doc.document_id} from {doc.invoice_amount or ''} "
                 f"requires your approval. Deadline: {approval.deadline.strftime('%d %b %Y %H:%M') if approval.deadline else 'N/A'}",
            action_url=f"/approvals/{approval.id}",
        )
        self.db.add(notif)
        self.db.flush()

    def _auto_approve_low_value(
        self, state: AgentState, doc: Document, document_id: str, amount: Decimal
    ) -> AgentState:
        log_audit(
            self.db,
            document_id=document_id,
            entity_type="APPROVAL",
            action="AUTO_APPROVED_LOW_VALUE",
            agent=self.name,
            log_metadata={
                "reason": f"Invoice total ₹{amount} is below ₹{AUTO_APPROVE_THRESHOLD} threshold with no validation failures — auto-approved",
            },
            stage=ProcessingStage.APPROVAL,
        )
        doc.status = DocumentStatus.APPROVED
        self.db.flush()
        update_workflow_stage(
            self.db, document_id=document_id,
            stage=ProcessingStage.ERP_POSTING,
            agent=self.name, progress_percent=90,
        )
        state.set_status("APPROVED")
        state.set_next_agent("ERP_POSTING_AGENT")
        return state

    def _auto_approve_no_rule(self, state: AgentState, doc: Document, document_id: str) -> AgentState:
        log_audit(
            self.db,
            document_id=document_id,
            entity_type="APPROVAL",
            action="AUTO_APPROVED_NO_RULE",
            agent=self.name,
            log_metadata={"reason": "No matching approval rule found — auto-approved"},
            stage=ProcessingStage.APPROVAL,
        )
        doc.status = DocumentStatus.APPROVED
        self.db.flush()

        update_workflow_stage(
            self.db, document_id=document_id,
            stage=ProcessingStage.ERP_POSTING,
            agent=self.name, progress_percent=90,
        )
        state.set_status("APPROVED")
        state.set_next_agent("ERP_POSTING_AGENT")
        return state
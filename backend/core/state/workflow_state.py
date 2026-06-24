"""
WorkflowState — the single shared state object for the entire AP Automation pipeline.

Every agent reads the full state and writes only to its designated section.
State is immutable-by-convention: use model_copy(update={...}) rather than
mutating fields in-place.

This is the central data contract for LangGraph orchestration.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Primitive / nested helpers
# ---------------------------------------------------------------------------

class LineItem(BaseModel):
    """Single line on an invoice."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    item_code: Optional[str] = None
    description: Optional[str] = None
    hsn_sac: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    uom: Optional[str] = None
    subtotal: Optional[Decimal] = None
    discount_amount: Optional[Decimal] = None
    tax_rate: Optional[float] = None
    cgst_amount: Optional[Decimal] = None
    sgst_amount: Optional[Decimal] = None
    igst_amount: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    total: Optional[Decimal] = None
    gl_code: Optional[str] = None
    cost_center: Optional[str] = None


class BankDetails(BaseModel):
    """Vendor bank account details from invoice."""

    account_name: Optional[str] = None
    account_number: Optional[str] = None
    bank_name: Optional[str] = None
    ifsc_code: Optional[str] = None
    swift_code: Optional[str] = None
    iban: Optional[str] = None


class ValidationError(BaseModel):
    """A single validation failure or warning."""

    field: Optional[str] = None
    rule: Optional[str] = None
    message: str
    severity: str = "ERROR"  # ERROR | WARNING
    error_code: Optional[str] = None
    actual_value: Optional[Any] = None
    expected_value: Optional[Any] = None


class Variance(BaseModel):
    """Difference between an invoice field and its reference value (PO/GRN)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    field: str
    invoice_value: Optional[Any] = None
    reference_value: Optional[Any] = None
    variance_amount: Optional[Decimal] = None
    variance_percent: Optional[float] = None
    within_tolerance: bool = False
    tolerance_threshold: Optional[float] = None


class ApprovalLevel(BaseModel):
    """One level in a multi-level approval chain."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    level: int
    approver_id: Optional[str] = None
    approver_name: Optional[str] = None
    authority_amount: Optional[Decimal] = None
    decision: Optional[str] = None  # APPROVED | REJECTED | PENDING | DELEGATED
    comments: Optional[str] = None
    decided_at: Optional[datetime] = None
    delegated_to: Optional[str] = None


class GLEntry(BaseModel):
    """A single debit or credit line in a journal entry."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    gl_code: str
    account_name: Optional[str] = None
    description: str
    debit: Optional[Decimal] = None
    credit: Optional[Decimal] = None
    cost_center: Optional[str] = None
    tax_code: Optional[str] = None


class ConfidenceFactor(BaseModel):
    """A single contributor to the overall confidence score."""

    name: str
    score: float
    weight: float
    positive: bool
    description: Optional[str] = None


class NotificationRecord(BaseModel):
    """Record of a single notification dispatch attempt."""

    recipient: str
    channel: str  # EMAIL | TEAMS | SMS | WEBHOOK
    event_type: str
    template_id: Optional[str] = None
    sent_at: Optional[datetime] = None
    status: str = "PENDING"  # PENDING | SENT | FAILED
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Agent output sections — each agent owns exactly one section
# ---------------------------------------------------------------------------

class DocumentInfo(BaseModel):
    """Populated by UploadAgent."""

    id: Optional[str] = None
    storage_path: Optional[str] = None
    original_filename: Optional[str] = None
    file_hash: Optional[str] = None
    file_size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    page_count: Optional[int] = None
    upload_timestamp: Optional[datetime] = None
    virus_scan_result: Optional[str] = None  # CLEAN | QUARANTINED | UNKNOWN


class ClassificationInfo(BaseModel):
    """Populated by ClassificationAgent."""

    document_class: Optional[str] = None  # DIGITAL | SCANNED | HANDWRITTEN | UNKNOWN
    ocr_strategy: Optional[str] = None    # BYPASS | TESSERACT | GPT_VISION
    image_quality_score: Optional[float] = None
    requires_enhancement: Optional[bool] = None
    language_hint: Optional[str] = None   # ISO 639-1 code, e.g. "en"
    confidence: Optional[float] = None
    low_quality: bool = False


class OCRInfo(BaseModel):
    """Populated by OCRAgent."""

    raw_text: Optional[str] = None
    page_texts: Optional[List[str]] = None
    confidence_scores: Optional[List[float]] = None
    avg_confidence: Optional[float] = None
    provider_used: Optional[str] = None   # TESSERACT | GPT_VISION | BYPASS
    enhancement_applied: bool = False
    word_count: Optional[int] = None
    low_confidence: bool = False


class InvoiceData(BaseModel):
    """Populated by ExtractionAgent — the canonical invoice data model."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Vendor
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    vendor_pan: Optional[str] = None
    vendor_vat: Optional[str] = None
    vendor_address: Optional[str] = None

    # Invoice header
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    payment_terms: Optional[str] = None
    currency: Optional[str] = None

    # Buyer
    buyer_name: Optional[str] = None
    buyer_gstin: Optional[str] = None
    buyer_address: Optional[str] = None
    cost_center: Optional[str] = None
    gl_code: Optional[str] = None

    # References
    po_number: Optional[str] = None
    grn_number: Optional[str] = None
    contract_number: Optional[str] = None
    lease_number: Optional[str] = None
    employee_code: Optional[str] = None

    # Amounts
    subtotal: Optional[Decimal] = None
    discount_amount: Optional[Decimal] = None
    cgst_amount: Optional[Decimal] = None
    sgst_amount: Optional[Decimal] = None
    igst_amount: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    tds_amount: Optional[Decimal] = None
    total_amount: Optional[Decimal] = None

    # Details
    line_items: Optional[List[LineItem]] = None
    bank_details: Optional[BankDetails] = None

    # Document metadata
    is_indian_document: bool = True
    language_code: Optional[str] = None
    was_translated: bool = False


class ExtractionMetadata(BaseModel):
    """Populated by ExtractionAgent — extraction quality metadata."""

    field_confidences: Optional[Dict[str, float]] = None
    missing_fields: Optional[List[str]] = None
    prompt_version: Optional[str] = None
    llm_model: Optional[str] = None
    token_count: Optional[int] = None
    reasoning: Optional[str] = None
    extraction_method: Optional[str] = None  # LLM | RULES


class ValidationInfo(BaseModel):
    """Populated by ValidationAgent."""

    is_valid: Optional[bool] = None
    errors: Optional[List[ValidationError]] = Field(default_factory=list)
    warnings: Optional[List[ValidationError]] = Field(default_factory=list)
    duplicate_check: Optional[Dict[str, Any]] = None
    arithmetic_check: Optional[Dict[str, Any]] = None
    gst_check: Optional[Dict[str, Any]] = None
    pan_check: Optional[Dict[str, Any]] = None
    date_check: Optional[Dict[str, Any]] = None


class ProfileInfo(BaseModel):
    """Populated by BusinessProfileAgent."""

    business_profile: Optional[str] = None
    profile_confidence: Optional[float] = None
    profile_reasoning: Optional[str] = None
    classification_method: Optional[str] = None  # AI | RULES | HYBRID
    alternative_profiles: Optional[List[str]] = None
    profile_signals: Optional[Dict[str, Any]] = None


class ProfileValidationInfo(BaseModel):
    """Populated by ProfileValidationAgent."""

    is_valid: Optional[bool] = None
    errors: Optional[List[ValidationError]] = Field(default_factory=list)
    warnings: Optional[List[ValidationError]] = Field(default_factory=list)
    required_references: Optional[Dict[str, Any]] = None


class POMatchResult(BaseModel):
    """PO matching outcome from POMatchingAgent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: Optional[str] = None  # MATCHED | PARTIAL | NOT_FOUND | SKIPPED
    match_score: Optional[float] = None
    variances: Optional[List[Variance]] = Field(default_factory=list)
    po_id: Optional[str] = None
    po_number: Optional[str] = None
    po_data: Optional[Dict[str, Any]] = None  # Cached PO from ERP


class GRNMatchResult(BaseModel):
    """GRN matching outcome from GRNMatchingAgent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: Optional[str] = None  # MATCHED | PARTIAL | NOT_FOUND | SKIPPED
    match_score: Optional[float] = None
    variances: Optional[List[Variance]] = Field(default_factory=list)
    grn_id: Optional[str] = None
    grn_number: Optional[str] = None
    grn_data: Optional[Dict[str, Any]] = None


class ThreeWayMatchResult(BaseModel):
    """Combined three-way match verdict from ThreeWayMatchingAgent."""

    disposition: Optional[str] = None  # FULL_MATCH | PARTIAL_MATCH | FAILED_MATCH
    overall_score: Optional[float] = None
    exception_required: bool = False
    approval_required: bool = False
    match_summary: Optional[str] = None


class MatchingInfo(BaseModel):
    """Populated by matching agents."""

    po_match: POMatchResult = Field(default_factory=POMatchResult)
    grn_match: GRNMatchResult = Field(default_factory=GRNMatchResult)
    three_way: ThreeWayMatchResult = Field(default_factory=ThreeWayMatchResult)


class ConfidenceInfo(BaseModel):
    """Populated by ConfidenceAgent."""

    overall_score: Optional[float] = None
    component_scores: Optional[Dict[str, float]] = None
    confidence_band: Optional[str] = None  # HIGH | MEDIUM | LOW | CRITICAL
    summary: Optional[str] = None
    contributing_factors: Optional[List[ConfidenceFactor]] = Field(default_factory=list)


class RoutingInfo(BaseModel):
    """Populated by ConfidenceAgent — controls LangGraph edge routing."""

    requires_human_review: bool = False
    auto_approve_eligible: bool = False
    review_reason: Optional[str] = None
    review_trigger: Optional[str] = None  # Which condition triggered review


class ExceptionInfo(BaseModel):
    """Populated by ExceptionAgent."""

    exception_id: Optional[str] = None
    exception_type: Optional[str] = None
    severity: Optional[str] = None         # LOW | MEDIUM | HIGH | CRITICAL
    assigned_queue: Optional[str] = None   # AP_TEAM | FINANCE | PROCUREMENT | COMPLIANCE | WAREHOUSE
    sla_deadline: Optional[datetime] = None
    resolution_status: Optional[str] = None  # OPEN | IN_PROGRESS | RESOLVED | ESCALATED
    assigned_to: Optional[str] = None
    escalation_level: int = 0
    resolution_type: Optional[str] = None  # AUTO_FIX | MANUAL_FIX | OVERRIDE | REJECT


class ApprovalInfo(BaseModel):
    """Populated by ApprovalAgent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    approval_id: Optional[str] = None
    approval_levels: Optional[List[ApprovalLevel]] = Field(default_factory=list)
    current_level: Optional[int] = None
    final_decision: Optional[str] = None  # APPROVED | REJECTED | PENDING
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    approver_comments: Optional[List[str]] = Field(default_factory=list)


class ERPInfo(BaseModel):
    """Populated by ERPPostingAgent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    posting_id: Optional[str] = None
    gl_entries: Optional[List[GLEntry]] = Field(default_factory=list)
    cost_centre: Optional[str] = None
    posting_status: Optional[str] = None  # POSTED | FAILED
    posted_at: Optional[datetime] = None
    erp_provider: Optional[str] = None    # MOCK | SAP | ORACLE | DYNAMICS | NETSUITE


class PaymentInfo(BaseModel):
    """Populated by PaymentAgent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    payment_id: Optional[str] = None
    due_date: Optional[date] = None
    gross_amount: Optional[Decimal] = None
    tds_amount: Optional[Decimal] = None
    net_payable: Optional[Decimal] = None
    payment_method: Optional[str] = None   # NEFT | RTGS | IMPS | CHEQUE
    payment_status: Optional[str] = None   # SCHEDULED | PENDING | PAID
    scheduled_date: Optional[date] = None


class HumanReviewInfo(BaseModel):
    """Populated by HumanReviewAgent."""

    reviewer_id: Optional[str] = None
    review_decision: Optional[str] = None  # APPROVED | REJECTED | CORRECTED
    corrections: Optional[Dict[str, Any]] = None
    review_comments: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    resume_node: Optional[str] = None
    flagged_fields: Optional[List[str]] = Field(default_factory=list)
    review_deadline: Optional[datetime] = None


class RetryInfo(BaseModel):
    """Populated by RetryAgent."""

    attempt_number: int = 0
    next_retry_at: Optional[datetime] = None
    backoff_seconds: Optional[int] = None
    escalated: bool = False
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None


class NotificationInfo(BaseModel):
    """Populated by NotificationAgent."""

    sent: List[NotificationRecord] = Field(default_factory=list)
    failed: List[NotificationRecord] = Field(default_factory=list)
    last_sent_at: Optional[datetime] = None


class AuditInfo(BaseModel):
    """Populated by AuditAgent."""

    last_event_id: Optional[str] = None
    event_count: int = 0
    trail_hash: Optional[str] = None


# ---------------------------------------------------------------------------
# Workflow metadata — updated by every agent
# ---------------------------------------------------------------------------

class WorkflowMetadata(BaseModel):
    """Core workflow metadata updated at every agent boundary."""

    document_id: str
    tenant_id: str = "default"
    status: str = "PENDING"
    current_agent: Optional[str] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    failed_agent: Optional[str] = None
    failure_reason: Optional[str] = None
    source_channel: str = "PORTAL"        # PORTAL | EMAIL | API | SFTP
    uploaded_by: Optional[str] = None
    processing_graph: Optional[str] = None  # Which LangGraph ran


# ---------------------------------------------------------------------------
# Root WorkflowState
# ---------------------------------------------------------------------------

class WorkflowState(BaseModel):
    """
    Central state object shared across all agents and LangGraph nodes.

    Rules:
    - Each agent reads the full state but writes ONLY to its designated section.
    - Use model_copy(deep=True, update={...}) for immutable updates.
    - Never mutate fields directly inside an agent.
    - The `workflow` section is updated by every agent (status, current_agent).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Core metadata
    workflow: WorkflowMetadata

    # Agent output sections (one per agent group)
    document: DocumentInfo = Field(default_factory=DocumentInfo)
    classification: ClassificationInfo = Field(default_factory=ClassificationInfo)
    ocr: OCRInfo = Field(default_factory=OCRInfo)
    invoice: InvoiceData = Field(default_factory=InvoiceData)
    extraction: ExtractionMetadata = Field(default_factory=ExtractionMetadata)
    validation: ValidationInfo = Field(default_factory=ValidationInfo)
    profile: ProfileInfo = Field(default_factory=ProfileInfo)
    profile_validation: ProfileValidationInfo = Field(default_factory=ProfileValidationInfo)
    matching: MatchingInfo = Field(default_factory=MatchingInfo)
    confidence: ConfidenceInfo = Field(default_factory=ConfidenceInfo)
    routing: RoutingInfo = Field(default_factory=RoutingInfo)
    exception: ExceptionInfo = Field(default_factory=ExceptionInfo)
    approval: ApprovalInfo = Field(default_factory=ApprovalInfo)
    erp: ERPInfo = Field(default_factory=ERPInfo)
    payment: PaymentInfo = Field(default_factory=PaymentInfo)
    human_review: HumanReviewInfo = Field(default_factory=HumanReviewInfo)
    retry: RetryInfo = Field(default_factory=RetryInfo)
    notifications: NotificationInfo = Field(default_factory=NotificationInfo)
    audit: AuditInfo = Field(default_factory=AuditInfo)

    # ---------------------------------------------------------------------------
    # Convenience methods (immutable — always return a new instance)
    # ---------------------------------------------------------------------------

    def with_status(self, status: str, agent: Optional[str] = None) -> "WorkflowState":
        """Return a copy with updated workflow status and agent name."""
        updates: Dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if agent is not None:
            updates["current_agent"] = agent
        return self.model_copy(
            deep=True,
            update={"workflow": self.workflow.model_copy(update=updates)},
        )

    def with_error(self, error_code: str, error_message: str, agent: str) -> "WorkflowState":
        """Return a copy with error information set."""
        return self.model_copy(
            deep=True,
            update={
                "workflow": self.workflow.model_copy(
                    update={
                        "status": "FAILED",
                        "error_code": error_code,
                        "error_message": error_message,
                        "failed_agent": agent,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
            },
        )

    def increment_retry(self) -> "WorkflowState":
        """Return a copy with retry count incremented."""
        return self.model_copy(
            deep=True,
            update={
                "workflow": self.workflow.model_copy(
                    update={"retry_count": self.workflow.retry_count + 1}
                ),
                "retry": self.retry.model_copy(
                    update={"attempt_number": self.retry.attempt_number + 1}
                ),
            },
        )

    def is_failed(self) -> bool:
        return self.workflow.status == "FAILED"

    def is_complete(self) -> bool:
        return self.workflow.status in ("COMPLETED", "REJECTED", "PAYMENT_SCHEDULED")

    def requires_review(self) -> bool:
        return self.routing.requires_human_review

    @classmethod
    def create(
        cls,
        document_id: str,
        tenant_id: str = "default",
        uploaded_by: Optional[str] = None,
        source_channel: str = "PORTAL",
    ) -> "WorkflowState":
        """Factory: create a fresh WorkflowState at the start of a new workflow."""
        return cls(
            workflow=WorkflowMetadata(
                document_id=document_id,
                tenant_id=tenant_id,
                status="UPLOADED",
                source_channel=source_channel,
                uploaded_by=uploaded_by,
            )
        )

from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class BaseSchema(BaseModel):
    model_config = {"from_attributes": True}


# ─── AUTH ─────────────────────────────────────────────────────────────────────

class Token(BaseSchema):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserCreate(BaseSchema):
    email: EmailStr
    name: str
    password: str = Field(min_length=8)
    role: str = "VIEWER"
    department: Optional[str] = None
    employee_code: Optional[str] = None


class UserUpdate(BaseSchema):
    name: Optional[str] = None
    department: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserOut(BaseSchema):
    id: str
    email: str
    name: str
    role: str
    department: Optional[str] = None
    employee_code: Optional[str] = None
    is_active: bool
    created_at: datetime


class PasswordChange(BaseSchema):
    current_password: str
    new_password: str = Field(min_length=8)


# ─── VENDOR ──────────────────────────────────────────────────────────────────

class VendorContactOut(BaseSchema):
    id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    designation: Optional[str] = None
    is_primary: bool
    contact_type: str


class VendorContactCreate(BaseSchema):
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    designation: Optional[str] = None
    is_primary: bool = False
    contact_type: str = "BILLING"


class VendorCreate(BaseSchema):
    vendor_code: str
    name: str
    gstin: Optional[str] = None
    pan: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: str = "India"
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc: Optional[str] = None
    bank_branch: Optional[str] = None
    payment_terms: str = "NET30"
    vendor_type: str = "GOODS"
    vendor_category: Optional[str] = None
    currency: str = "INR"
    credit_limit: Decimal = Decimal("0")
    is_approved: bool = False
    is_msme: bool = False
    tds_applicable: bool = False
    tds_rate: Decimal = Decimal("0")
    po_required: bool = False
    contacts: List[VendorContactCreate] = []

    @field_validator("gstin")
    @classmethod
    def validate_gstin(cls, v):
        if v and len(v) != 15:
            raise ValueError("GSTIN must be 15 characters")
        return v

    @field_validator("pan")
    @classmethod
    def validate_pan(cls, v):
        import re
        if v and not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$", v):
            raise ValueError("Invalid PAN format")
        return v


class VendorUpdate(BaseSchema):
    name: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    address_line1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc: Optional[str] = None
    payment_terms: Optional[str] = None
    is_approved: Optional[bool] = None
    tds_applicable: Optional[bool] = None
    tds_rate: Optional[Decimal] = None


class VendorOut(BaseSchema):
    id: str
    vendor_code: str
    name: str
    gstin: Optional[str] = None
    pan: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    payment_terms: str
    vendor_type: str
    currency: str
    credit_limit: Decimal
    is_approved: bool
    is_msme: bool
    tds_applicable: bool
    tds_rate: Decimal
    po_required: bool = False
    created_at: datetime
    contacts: List[VendorContactOut] = []


class VendorListOut(BaseSchema):
    id: str
    vendor_code: str
    name: str
    gstin: Optional[str] = None
    pan: Optional[str] = None
    city: Optional[str] = None
    payment_terms: str
    vendor_type: str
    is_approved: bool
    created_at: datetime


# ─── COST CENTER & GL CODE ───────────────────────────────────────────────────

class CostCenterCreate(BaseSchema):
    code: str
    name: str
    department: Optional[str] = None
    description: Optional[str] = None
    approver_id: Optional[str] = None


class CostCenterOut(BaseSchema):
    id: str
    code: str
    name: str
    department: Optional[str] = None
    is_active: bool


class GLCodeCreate(BaseSchema):
    code: str
    name: str
    category: Optional[str] = None
    sub_category: Optional[str] = None
    account_type: Optional[str] = None
    description: Optional[str] = None


class GLCodeOut(BaseSchema):
    id: str
    code: str
    name: str
    category: Optional[str] = None
    sub_category: Optional[str] = None
    is_active: bool


# ─── PURCHASE ORDER ──────────────────────────────────────────────────────────

class POLineItemCreate(BaseSchema):
    line_number: int
    item_code: Optional[str] = None
    description: str
    hsn_sac_code: Optional[str] = None
    quantity: Decimal
    unit_price: Decimal
    uom: str
    discount_percent: Decimal = Decimal("0")
    total_amount: Decimal
    gl_code_id: Optional[str] = None
    asset_category: Optional[str] = None
    tax_code: Optional[str] = None
    cgst_rate: Decimal = Decimal("0")
    sgst_rate: Decimal = Decimal("0")
    igst_rate: Decimal = Decimal("0")


class POLineItemOut(BaseSchema):
    id: str
    line_number: int
    item_code: Optional[str] = None
    description: str
    hsn_sac_code: Optional[str] = None
    quantity: Decimal
    received_quantity: Decimal
    invoiced_quantity: Decimal
    unit_price: Decimal
    uom: str
    total_amount: Decimal
    cgst_rate: Decimal
    sgst_rate: Decimal
    igst_rate: Decimal


class PurchaseOrderCreate(BaseSchema):
    po_number: str
    vendor_id: str
    total_amount: Decimal
    currency: str = "INR"
    cost_center_id: Optional[str] = None
    gl_code_id: Optional[str] = None
    payment_terms: str = "NET30"
    delivery_date: Optional[date] = None
    po_date: date
    description: Optional[str] = None
    line_items: List[POLineItemCreate] = []


class PurchaseOrderUpdate(BaseSchema):
    status: Optional[str] = None
    payment_terms: Optional[str] = None
    delivery_date: Optional[date] = None
    description: Optional[str] = None


class PurchaseOrderOut(BaseSchema):
    id: str
    po_number: str
    vendor_id: str
    vendor_name: Optional[str] = None
    status: str
    total_amount: Decimal
    invoiced_amount: Decimal
    currency: str
    payment_terms: str
    po_date: date
    delivery_date: Optional[date] = None
    created_at: datetime
    line_items: List[POLineItemOut] = []


class PurchaseOrderListOut(BaseSchema):
    id: str
    po_number: str
    vendor_id: str
    vendor_name: Optional[str] = None
    status: str
    total_amount: Decimal
    currency: str
    po_date: date
    created_at: datetime


# ─── GRN ─────────────────────────────────────────────────────────────────────

class GRNLineItemCreate(BaseSchema):
    po_line_id: str
    received_quantity: Decimal
    accepted_quantity: Decimal
    rejected_quantity: Decimal = Decimal("0")
    rejection_reason: Optional[str] = None
    batch_number: Optional[str] = None
    uom: str


class GRNLineItemOut(BaseSchema):
    id: str
    po_line_id: str
    received_quantity: Decimal
    accepted_quantity: Decimal
    rejected_quantity: Decimal
    rejection_reason: Optional[str] = None
    uom: str


class GRNCreate(BaseSchema):
    grn_number: str
    po_id: str
    vendor_id: str
    received_date: date
    warehouse_location: Optional[str] = None
    vehicle_number: Optional[str] = None
    transporter: Optional[str] = None
    delivery_challan_number: Optional[str] = None
    quality_check_passed: Optional[bool] = None
    remarks: Optional[str] = None
    line_items: List[GRNLineItemCreate] = []


class GRNOut(BaseSchema):
    id: str
    grn_number: str
    po_id: str
    po_number: Optional[str] = None
    vendor_id: str
    vendor_name: Optional[str] = None
    received_date: date
    status: str
    warehouse_location: Optional[str] = None
    created_at: datetime
    line_items: List[GRNLineItemOut] = []


# ─── CONTRACT ────────────────────────────────────────────────────────────────

class ContractCreate(BaseSchema):
    contract_number: str
    vendor_id: str
    contract_type: str
    title: Optional[str] = None
    description: Optional[str] = None
    start_date: date
    end_date: date
    value: Decimal
    currency: str = "INR"
    payment_terms: str = "NET30"
    auto_renewal: bool = False
    notice_period_days: int = 30
    cost_center_id: Optional[str] = None
    gl_code_id: Optional[str] = None


class ContractOut(BaseSchema):
    id: str
    contract_number: str
    vendor_id: str
    vendor_name: Optional[str] = None
    contract_type: str
    title: Optional[str] = None
    start_date: date
    end_date: date
    value: Decimal
    currency: str
    status: str
    created_at: datetime


class LeaseContractCreate(BaseSchema):
    contract_number: str
    vendor_id: str
    property_name: str
    property_address: str
    property_type: Optional[str] = None
    area_sqft: Optional[Decimal] = None
    monthly_rent: Decimal
    security_deposit: Decimal = Decimal("0")
    lease_start: date
    lease_end: date
    lock_in_period_months: int = 0
    gst_applicable: bool = True
    gst_rate: Decimal = Decimal("18")
    tds_rate: Decimal = Decimal("10")
    escalation_percent: Decimal = Decimal("0")
    cost_center_id: Optional[str] = None
    gl_code_id: Optional[str] = None


class LeaseContractOut(BaseSchema):
    id: str
    contract_number: str
    vendor_id: str
    vendor_name: Optional[str] = None
    property_name: str
    property_address: str
    monthly_rent: Decimal
    lease_start: date
    lease_end: date
    gst_applicable: bool
    gst_rate: Decimal
    tds_rate: Decimal
    status: str


# ─── ASSET ───────────────────────────────────────────────────────────────────

class AssetCreate(BaseSchema):
    asset_code: str
    name: str
    category: str
    sub_category: Optional[str] = None
    description: Optional[str] = None
    serial_number: Optional[str] = None
    model_number: Optional[str] = None
    make: Optional[str] = None
    vendor_id: Optional[str] = None
    purchase_date: Optional[date] = None
    purchase_value: Optional[Decimal] = None
    location: Optional[str] = None
    department: Optional[str] = None
    cost_center_id: Optional[str] = None
    gl_code_id: Optional[str] = None
    depreciation_rate: Decimal = Decimal("0")
    useful_life_years: Optional[int] = None


class AssetOut(BaseSchema):
    id: str
    asset_code: str
    name: str
    category: str
    serial_number: Optional[str] = None
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    purchase_date: Optional[date] = None
    purchase_value: Optional[Decimal] = None
    current_value: Optional[Decimal] = None
    location: Optional[str] = None
    status: str
    capitalized: bool
    created_at: datetime


# ─── EMPLOYEE ────────────────────────────────────────────────────────────────

class EmployeeCreate(BaseSchema):
    employee_code: str
    name: str
    email: EmailStr
    phone: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    grade: Optional[str] = None
    cost_center_id: Optional[str] = None
    monthly_reimbursement_limit: Decimal = Decimal("0")
    petty_cash_limit: Decimal = Decimal("0")
    daily_petty_cash_limit: Decimal = Decimal("0")
    joining_date: Optional[date] = None


class EmployeeOut(BaseSchema):
    id: str
    employee_code: str
    name: str
    email: str
    department: Optional[str] = None
    designation: Optional[str] = None
    monthly_reimbursement_limit: Decimal
    petty_cash_limit: Decimal
    is_active: bool


# ─── BUDGET ──────────────────────────────────────────────────────────────────

class BudgetCreate(BaseSchema):
    cost_center_id: str
    gl_code_id: str
    fiscal_year: str
    period: str = "ANNUAL"
    total_amount: Decimal
    currency: str = "INR"


class BudgetOut(BaseSchema):
    id: str
    cost_center_id: str
    cost_center_name: Optional[str] = None
    gl_code_id: str
    gl_code_name: Optional[str] = None
    fiscal_year: str
    period: str
    total_amount: Decimal
    committed_amount: Decimal
    spent_amount: Decimal
    available_amount: Decimal
    currency: str


# ─── DOCUMENT ────────────────────────────────────────────────────────────────

class DocumentUploadResponse(BaseSchema):
    document_id: str
    filename: str
    status: str
    task_id: str
    message: str


class DocumentListOut(BaseSchema):
    id: str
    document_id: str
    original_filename: str
    status: str
    doc_type: Optional[str] = None
    business_profile: Optional[str] = None
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    ai_profile_confidence: Optional[Decimal] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    total_amount: Optional[Decimal] = None
    currency: str
    ingestion_source: str
    created_at: datetime


class DocumentOut(BaseSchema):
    id: str
    document_id: str
    original_filename: str
    file_extension: str
    file_size: int
    status: str
    doc_type: Optional[str] = None
    business_profile: Optional[str] = None
    ai_profile_confidence: Optional[Decimal] = None
    ai_profile_reasoning: Optional[str] = None
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    po_id: Optional[str] = None
    po_number: Optional[str] = None
    grn_id: Optional[str] = None
    grn_number: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    invoice_amount: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    total_amount: Optional[Decimal] = None
    currency: str
    extracted_data: Optional[Dict[str, Any]] = None
    ocr_confidence: Optional[Decimal] = None
    ocr_text: Optional[str] = None
    ingestion_source: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    line_items: List["DocumentLineItemOut"] = []


class DocumentLineItemOut(BaseSchema):
    id: str
    line_number: int
    description: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    uom: Optional[str] = None
    cgst_rate: Decimal
    sgst_rate: Decimal
    igst_rate: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_amount: Optional[Decimal] = None
    gl_code: Optional[str] = None
    cost_center: Optional[str] = None


# ─── WORKFLOW ────────────────────────────────────────────────────────────────

class WorkflowStateOut(BaseSchema):
    id: str
    document_id: str
    current_stage: str
    current_agent: Optional[str] = None
    progress_percent: int
    error_message: Optional[str] = None
    stage_history: List[Dict[str, Any]] = []
    retry_count: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ─── VALIDATION ──────────────────────────────────────────────────────────────

class ValidationRuleCreate(BaseSchema):
    rule_code: str
    rule_name: str
    rule_type: str
    severity: str = "FAIL"
    parameters: Dict[str, Any] = {}
    error_message: Optional[str] = None
    sort_order: int = 0


class ValidationRuleOut(BaseSchema):
    id: str
    rule_code: str
    rule_name: str
    rule_type: str
    severity: str
    parameters: Dict[str, Any]
    error_message: Optional[str] = None
    is_active: bool
    sort_order: int


class ValidationProfileCreate(BaseSchema):
    name: str
    business_profile: str
    description: Optional[str] = None
    rules: List[ValidationRuleCreate] = []


class ValidationProfileOut(BaseSchema):
    id: str
    name: str
    business_profile: str
    description: Optional[str] = None
    is_active: bool
    rules: List[ValidationRuleOut] = []


class ValidationResultOut(BaseSchema):
    id: str
    rule_code: str
    rule_name: Optional[str] = None
    status: str
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None
    reason: Optional[str] = None
    severity: Optional[str] = None
    agent: Optional[str] = None
    created_at: datetime


# ─── MATCHING ────────────────────────────────────────────────────────────────

class MatchingResultOut(BaseSchema):
    id: str
    document_id: str
    po_id: Optional[str] = None
    po_number: Optional[str] = None
    grn_id: Optional[str] = None
    grn_number: Optional[str] = None
    match_status: str
    overall_match_score: Decimal
    quantity_match: Optional[bool] = None
    price_match: Optional[bool] = None
    tax_match: Optional[bool] = None
    total_match: Optional[bool] = None
    vendor_match: Optional[bool] = None
    variance_report: Optional[Dict[str, Any]] = None
    line_matches: Optional[List[Dict[str, Any]]] = None
    tolerance_applied: bool
    matching_notes: Optional[str] = None
    created_at: datetime


# ─── EXCEPTIONS ──────────────────────────────────────────────────────────────

class ExceptionOut(BaseSchema):
    id: str
    document_id: str
    exception_code: str
    exception_type: str
    severity: str
    queue: str
    title: str
    description: Optional[str] = None
    agent_raised_by: Optional[str] = None
    assigned_to: Optional[str] = None
    assignee_name: Optional[str] = None
    status: str
    sla_hours: int
    sla_deadline: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    resolved_at: Optional[datetime] = None
    escalation_count: int
    created_at: datetime


class ExceptionResolve(BaseSchema):
    resolution_notes: str
    status: str = "RESOLVED"


class ExceptionAssign(BaseSchema):
    assigned_to: str


# ─── APPROVALS ───────────────────────────────────────────────────────────────

class ApprovalRuleCreate(BaseSchema):
    name: str
    business_profile: Optional[str] = None
    amount_min: Decimal = Decimal("0")
    amount_max: Optional[Decimal] = None
    conditions: Dict[str, Any] = {}
    approval_matrix: List[Dict[str, Any]]
    priority: int = 0


class ApprovalRuleOut(BaseSchema):
    id: str
    name: str
    business_profile: Optional[str] = None
    amount_min: Decimal
    amount_max: Optional[Decimal] = None
    approval_matrix: List[Dict[str, Any]]
    is_active: bool
    priority: int


class ApprovalOut(BaseSchema):
    id: str
    document_id: str
    approval_level: int
    approver_id: str
    approver_name: Optional[str] = None
    delegate_id: Optional[str] = None
    status: str
    action: Optional[str] = None
    comments: Optional[str] = None
    actioned_at: Optional[datetime] = None
    deadline: Optional[datetime] = None
    created_at: datetime


class ApprovalAction(BaseSchema):
    action: str
    comments: Optional[str] = None


# ─── AUDIT LOG ───────────────────────────────────────────────────────────────

class AuditLogOut(BaseSchema):
    id: str
    document_id: Optional[str] = None
    entity_type: str
    entity_id: Optional[str] = None
    action: str
    agent: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    before_state: Optional[Dict[str, Any]] = None
    after_state: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    stage: Optional[str] = None
    timestamp: datetime


# ─── PAYMENT SCHEDULE ─────────────────────────────────────────────────────────

class PaymentScheduleOut(BaseSchema):
    id: str
    document_id: str
    vendor_id: str
    vendor_name: Optional[str] = None
    invoice_amount: Decimal
    tax_amount: Decimal
    tds_deduction: Decimal
    net_payable: Decimal
    payment_terms: str
    invoice_date: date
    due_date: date
    status: str
    payment_reference: Optional[str] = None
    paid_at: Optional[datetime] = None


# ─── ERP POSTING ─────────────────────────────────────────────────────────────

class ERPPostingOut(BaseSchema):
    id: str
    document_id: str
    posting_date: date
    fiscal_period: Optional[str] = None
    journal_entries: List[Dict[str, Any]]
    erp_reference: Optional[str] = None
    erp_system: str
    posting_status: str
    error_message: Optional[str] = None
    created_at: datetime


# ─── DASHBOARD ───────────────────────────────────────────────────────────────

class DashboardStats(BaseSchema):
    total_documents: int
    documents_today: int
    pending_approvals: int
    open_exceptions: int
    matching_rate: Decimal
    avg_processing_time_minutes: Optional[Decimal] = None
    total_invoice_amount: Decimal
    documents_by_status: Dict[str, int]
    documents_by_profile: Dict[str, int]
    documents_by_source: Dict[str, int]
    exception_by_queue: Dict[str, int]
    top_vendors_by_amount: List[Dict[str, Any]]
    processing_trend: List[Dict[str, Any]]
    approval_sla_stats: Dict[str, Any]


# ─── PAGINATION ──────────────────────────────────────────────────────────────

class PaginatedResponse(BaseSchema):
    items: List[Any]
    total: int
    page: int
    page_size: int
    total_pages: int


class PaginationParams(BaseSchema):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)


# ─── CONFIG ──────────────────────────────────────────────────────────────────

class ConfigurationOut(BaseSchema):
    id: str
    key: str
    value: str
    category: str
    description: Optional[str] = None
    value_type: str
    is_active: bool


class ConfigurationUpdate(BaseSchema):
    value: str
    is_active: Optional[bool] = None
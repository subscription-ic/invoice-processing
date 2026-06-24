from __future__ import annotations

import uuid
from datetime import datetime, date, timezone
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric,
    String, Text, JSON, Enum as SAEnum, BigInteger, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.base import Base


def utcnow():
    return datetime.now(timezone.utc)


def new_uuid():
    return str(uuid.uuid4())


# ─── ENUM CONSTANTS ──────────────────────────────────────────────────────────

class UserRole:
    ADMIN = "ADMIN"
    AP_TEAM = "AP_TEAM"
    FINANCE = "FINANCE"
    APPROVER = "APPROVER"
    PROCUREMENT = "PROCUREMENT"
    VIEWER = "VIEWER"

class DocumentStatus:
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    EXTRACTING = "EXTRACTING"
    VALIDATING = "VALIDATING"
    MATCHING = "MATCHING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    POSTED = "POSTED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    EXCEPTION = "EXCEPTION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    # Phase 4+ LangGraph pipeline statuses
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    UNDER_REVIEW = "UNDER_REVIEW"
    PAYMENT_SCHEDULED = "PAYMENT_SCHEDULED"
    PROFILED = "PROFILED"
    EXCEPTION_RESOLVED = "EXCEPTION_RESOLVED"

class DocType:
    DIGITAL = "DIGITAL"
    SCANNED = "SCANNED"
    HANDWRITTEN = "HANDWRITTEN"

class BusinessProfile:
    PO_RAW_MATERIAL = "PO_RAW_MATERIAL"
    NON_PO_RAW_MATERIAL = "NON_PO_RAW_MATERIAL"
    PO_CAPEX = "PO_CAPEX"
    NON_PO_CAPEX = "NON_PO_CAPEX"
    PO_OPEX = "PO_OPEX"
    NON_PO_OPEX = "NON_PO_OPEX"
    LEASE_RENT = "LEASE_RENT"
    EMPLOYEE_REIMBURSEMENT = "EMPLOYEE_REIMBURSEMENT"
    PETTY_CASH = "PETTY_CASH"

class ProcessingStage:
    INTAKE = "INTAKE"
    DOCUMENT_CLASSIFICATION = "DOCUMENT_CLASSIFICATION"
    OCR = "OCR"
    EXTRACTION = "EXTRACTION"
    UNIVERSAL_VALIDATION = "UNIVERSAL_VALIDATION"
    BUSINESS_PROFILE_PREDICTION = "BUSINESS_PROFILE_PREDICTION"
    PROFILE_VALIDATION = "PROFILE_VALIDATION"
    MATCHING = "MATCHING"
    APPROVAL = "APPROVAL"
    ERP_POSTING = "ERP_POSTING"
    PAYMENT_SCHEDULING = "PAYMENT_SCHEDULING"
    COMPLETED = "COMPLETED"
    EXCEPTION = "EXCEPTION"

class ValidationStatus:
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"

class MatchStatus:
    MATCHED = "MATCHED"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    MISMATCH = "MISMATCH"
    TOLERANCE_MATCH = "TOLERANCE_MATCH"
    NOT_APPLICABLE = "NOT_APPLICABLE"

class ApprovalStatus:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    DELEGATED = "DELEGATED"

class ExceptionSeverity:
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class ExceptionQueue:
    AP_TEAM = "AP_TEAM"
    FINANCE = "FINANCE"
    PROCUREMENT = "PROCUREMENT"
    COMPLIANCE = "COMPLIANCE"
    WAREHOUSE = "WAREHOUSE"

class ExceptionStatus:
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"

class POStatus:
    OPEN = "OPEN"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    FULLY_RECEIVED = "FULLY_RECEIVED"
    INVOICED = "INVOICED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"

class GRNStatus:
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"

class ERPSystem:
    MOCK = "MOCK"
    SAP = "SAP"
    ORACLE = "ORACLE"
    DYNAMICS = "DYNAMICS"
    TALLY = "TALLY"

class PaymentStatus:
    SCHEDULED = "SCHEDULED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


# ─── AUTH & USERS ─────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default=UserRole.VIEWER)
    department = Column(String(100))
    employee_code = Column(String(50))
    is_active = Column(Boolean, default=True, nullable=False)
    is_superuser = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_login = Column(DateTime(timezone=True))

    documents = relationship("Document", back_populates="uploader", foreign_keys="Document.uploaded_by")
    approvals = relationship("Approval", back_populates="approver", foreign_keys="Approval.approver_id")
    audit_logs = relationship("AuditLog", back_populates="user", foreign_keys="AuditLog.user_id")
    notifications = relationship("Notification", back_populates="user")


# ─── ERP MASTER DATA ──────────────────────────────────────────────────────────

class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    vendor_code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    gstin = Column(String(15), index=True)
    pan = Column(String(10), index=True)
    address_line1 = Column(String(255))
    address_line2 = Column(String(255))
    city = Column(String(100))
    state = Column(String(100))
    pincode = Column(String(10))
    country = Column(String(50), default="India")
    bank_name = Column(String(255))
    bank_account_number = Column(String(50))
    bank_ifsc = Column(String(20))
    bank_branch = Column(String(255))
    payment_terms = Column(String(20), default="NET30")
    vendor_type = Column(String(20), default="GOODS")
    vendor_category = Column(String(50))
    currency = Column(String(10), default="INR")
    credit_limit = Column(Numeric(18, 2), default=0)
    is_approved = Column(Boolean, default=False)
    is_msme = Column(Boolean, default=False)
    msme_registration = Column(String(50))
    tds_applicable = Column(Boolean, default=False)
    tds_rate = Column(Numeric(5, 2), default=0)
    # When True, ALL invoices from this vendor must be backed by a PO (blanket/standing PO).
    po_required = Column(Boolean, default=False)
    # Phase 6 additions
    tds_category = Column(String(50))           # TDS rate category (194C / 194J / etc.)
    payment_method = Column(String(20))         # NEFT | RTGS | IMPS | CHEQUE
    bank_account_changed_at = Column(DateTime(timezone=True))  # Anti-fraud: last bank detail change
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    contacts = relationship("VendorContact", back_populates="vendor", cascade="all, delete-orphan")
    purchase_orders = relationship("PurchaseOrder", back_populates="vendor")
    grns = relationship("GRN", back_populates="vendor")
    contracts = relationship("Contract", back_populates="vendor")
    lease_contracts = relationship("LeaseContract", back_populates="vendor")
    assets = relationship("Asset", back_populates="vendor")
    documents = relationship("Document", back_populates="vendor")
    payment_schedules = relationship("PaymentSchedule", back_populates="vendor")


class VendorContact(Base):
    __tablename__ = "vendor_contacts"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    vendor_id = Column(UUID(as_uuid=False), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    email = Column(String(255))
    phone = Column(String(20))
    designation = Column(String(100))
    is_primary = Column(Boolean, default=False)
    contact_type = Column(String(50), default="BILLING")

    vendor = relationship("Vendor", back_populates="contacts")


class CostCenter(Base):
    __tablename__ = "cost_centers"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    department = Column(String(100))
    description = Column(String(255))
    parent_id = Column(UUID(as_uuid=False), ForeignKey("cost_centers.id"))
    approver_id = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    parent = relationship("CostCenter", remote_side="CostCenter.id")
    approver = relationship("User", foreign_keys=[approver_id])
    budgets = relationship("Budget", back_populates="cost_center")
    employees = relationship("Employee", back_populates="cost_center")
    assets = relationship("Asset", back_populates="cost_center")


class GLCode(Base):
    __tablename__ = "gl_codes"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    category = Column(String(50))
    sub_category = Column(String(50))
    account_type = Column(String(10))
    description = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    po_number = Column(String(50), unique=True, nullable=False, index=True)
    vendor_id = Column(UUID(as_uuid=False), ForeignKey("vendors.id"), nullable=False)
    status = Column(String(30), default=POStatus.OPEN, nullable=False)
    total_amount = Column(Numeric(18, 2), nullable=False, default=0)
    invoiced_amount = Column(Numeric(18, 2), default=0)
    currency = Column(String(10), default="INR")
    cost_center_id = Column(UUID(as_uuid=False), ForeignKey("cost_centers.id"))
    gl_code_id = Column(UUID(as_uuid=False), ForeignKey("gl_codes.id"))
    payment_terms = Column(String(20), default="NET30")
    delivery_date = Column(Date)
    po_date = Column(Date, nullable=False)
    description = Column(Text)
    terms_and_conditions = Column(Text)
    created_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    approved_by = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    approved_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    vendor = relationship("Vendor", back_populates="purchase_orders")
    cost_center = relationship("CostCenter")
    gl_code = relationship("GLCode")
    created_by_user = relationship("User", foreign_keys=[created_by])
    approved_by_user = relationship("User", foreign_keys=[approved_by])
    line_items = relationship("POLineItem", back_populates="purchase_order", cascade="all, delete-orphan")
    grns = relationship("GRN", back_populates="purchase_order")
    documents = relationship("Document", back_populates="purchase_order")


class POLineItem(Base):
    __tablename__ = "po_line_items"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    po_id = Column(UUID(as_uuid=False), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    line_number = Column(Integer, nullable=False)
    item_code = Column(String(50))
    description = Column(Text, nullable=False)
    hsn_sac_code = Column(String(10))
    quantity = Column(Numeric(18, 4), nullable=False)
    received_quantity = Column(Numeric(18, 4), default=0)
    invoiced_quantity = Column(Numeric(18, 4), default=0)
    unit_price = Column(Numeric(18, 4), nullable=False)
    uom = Column(String(20), nullable=False)
    discount_percent = Column(Numeric(5, 2), default=0)
    total_amount = Column(Numeric(18, 2), nullable=False)
    gl_code_id = Column(UUID(as_uuid=False), ForeignKey("gl_codes.id"))
    asset_category = Column(String(100))
    tax_code = Column(String(20))
    cgst_rate = Column(Numeric(5, 2), default=0)
    sgst_rate = Column(Numeric(5, 2), default=0)
    igst_rate = Column(Numeric(5, 2), default=0)

    purchase_order = relationship("PurchaseOrder", back_populates="line_items")
    gl_code = relationship("GLCode")
    grn_line_items = relationship("GRNLineItem", back_populates="po_line_item")


class GRN(Base):
    __tablename__ = "grns"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    grn_number = Column(String(50), unique=True, nullable=False, index=True)
    po_id = Column(UUID(as_uuid=False), ForeignKey("purchase_orders.id"), nullable=False)
    vendor_id = Column(UUID(as_uuid=False), ForeignKey("vendors.id"), nullable=False)
    received_date = Column(Date, nullable=False)
    status = Column(String(20), default=GRNStatus.PENDING, nullable=False)
    received_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    warehouse_location = Column(String(255))
    vehicle_number = Column(String(20))
    transporter = Column(String(100))
    delivery_challan_number = Column(String(50))
    quality_check_passed = Column(Boolean)
    remarks = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    purchase_order = relationship("PurchaseOrder", back_populates="grns")
    vendor = relationship("Vendor", back_populates="grns")
    received_by_user = relationship("User", foreign_keys=[received_by])
    line_items = relationship("GRNLineItem", back_populates="grn", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="grn")


class GRNLineItem(Base):
    __tablename__ = "grn_line_items"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    grn_id = Column(UUID(as_uuid=False), ForeignKey("grns.id", ondelete="CASCADE"), nullable=False)
    po_line_id = Column(UUID(as_uuid=False), ForeignKey("po_line_items.id"), nullable=False)
    received_quantity = Column(Numeric(18, 4), nullable=False)
    accepted_quantity = Column(Numeric(18, 4), nullable=False)
    rejected_quantity = Column(Numeric(18, 4), default=0)
    rejection_reason = Column(Text)
    batch_number = Column(String(50))
    expiry_date = Column(Date)
    uom = Column(String(20))

    grn = relationship("GRN", back_populates="line_items")
    po_line_item = relationship("POLineItem", back_populates="grn_line_items")


class Contract(Base):
    __tablename__ = "contracts"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    contract_number = Column(String(50), unique=True, nullable=False, index=True)
    vendor_id = Column(UUID(as_uuid=False), ForeignKey("vendors.id"), nullable=False)
    contract_type = Column(String(50), nullable=False)
    title = Column(String(255))
    description = Column(Text)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    value = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(10), default="INR")
    status = Column(String(20), default="ACTIVE")
    payment_terms = Column(String(20), default="NET30")
    auto_renewal = Column(Boolean, default=False)
    notice_period_days = Column(Integer, default=30)
    scope_of_work = Column(Text)
    sla_terms = Column(Text)
    cost_center_id = Column(UUID(as_uuid=False), ForeignKey("cost_centers.id"))
    gl_code_id = Column(UUID(as_uuid=False), ForeignKey("gl_codes.id"))
    created_by = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    vendor = relationship("Vendor", back_populates="contracts")
    cost_center = relationship("CostCenter")
    gl_code = relationship("GLCode")
    documents = relationship("Document", back_populates="contract")


class LeaseContract(Base):
    __tablename__ = "lease_contracts"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    contract_number = Column(String(50), unique=True, nullable=False, index=True)
    vendor_id = Column(UUID(as_uuid=False), ForeignKey("vendors.id"), nullable=False)
    property_name = Column(String(255), nullable=False)
    property_address = Column(Text, nullable=False)
    property_type = Column(String(50))
    area_sqft = Column(Numeric(12, 2))
    monthly_rent = Column(Numeric(18, 2), nullable=False)
    security_deposit = Column(Numeric(18, 2), default=0)
    lease_start = Column(Date, nullable=False)
    lease_end = Column(Date, nullable=False)
    lock_in_period_months = Column(Integer, default=0)
    gst_applicable = Column(Boolean, default=True)
    gst_rate = Column(Numeric(5, 2), default=18)
    tds_rate = Column(Numeric(5, 2), default=10)
    escalation_percent = Column(Numeric(5, 2), default=0)
    escalation_frequency_months = Column(Integer, default=12)
    currency = Column(String(10), default="INR")
    status = Column(String(20), default="ACTIVE")
    cost_center_id = Column(UUID(as_uuid=False), ForeignKey("cost_centers.id"))
    gl_code_id = Column(UUID(as_uuid=False), ForeignKey("gl_codes.id"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    vendor = relationship("Vendor", back_populates="lease_contracts")
    cost_center = relationship("CostCenter")
    gl_code = relationship("GLCode")


class Asset(Base):
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    asset_code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False)
    sub_category = Column(String(50))
    description = Column(Text)
    serial_number = Column(String(100))
    model_number = Column(String(100))
    make = Column(String(100))
    vendor_id = Column(UUID(as_uuid=False), ForeignKey("vendors.id"))
    purchase_date = Column(Date)
    purchase_value = Column(Numeric(18, 2))
    current_value = Column(Numeric(18, 2))
    depreciation_rate = Column(Numeric(5, 2), default=0)
    useful_life_years = Column(Integer)
    location = Column(String(255))
    department = Column(String(100))
    cost_center_id = Column(UUID(as_uuid=False), ForeignKey("cost_centers.id"))
    gl_code_id = Column(UUID(as_uuid=False), ForeignKey("gl_codes.id"))
    status = Column(String(30), default="ACTIVE")
    assigned_to = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    asset_tag = Column(String(100))
    warranty_expiry = Column(Date)
    capitalized = Column(Boolean, default=False)
    capitalization_date = Column(Date)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    vendor = relationship("Vendor", back_populates="assets")
    cost_center = relationship("CostCenter", back_populates="assets")
    gl_code = relationship("GLCode")
    assigned_user = relationship("User", foreign_keys=[assigned_to])


class Employee(Base):
    __tablename__ = "employees"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    employee_code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone = Column(String(20))
    department = Column(String(100))
    designation = Column(String(100))
    grade = Column(String(20))
    manager_id = Column(UUID(as_uuid=False), ForeignKey("employees.id"))
    cost_center_id = Column(UUID(as_uuid=False), ForeignKey("cost_centers.id"))
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), unique=True)
    monthly_reimbursement_limit = Column(Numeric(10, 2), default=0)
    petty_cash_limit = Column(Numeric(10, 2), default=0)
    daily_petty_cash_limit = Column(Numeric(10, 2), default=0)
    joining_date = Column(Date)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    manager = relationship("Employee", remote_side="Employee.id")
    cost_center = relationship("CostCenter", back_populates="employees")
    user = relationship("User")
    documents = relationship("Document", back_populates="employee")


class Budget(Base):
    __tablename__ = "budgets"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    cost_center_id = Column(UUID(as_uuid=False), ForeignKey("cost_centers.id"), nullable=False)
    gl_code_id = Column(UUID(as_uuid=False), ForeignKey("gl_codes.id"), nullable=False)
    fiscal_year = Column(String(10), nullable=False)
    period = Column(String(10), default="ANNUAL")
    total_amount = Column(Numeric(18, 2), nullable=False, default=0)
    committed_amount = Column(Numeric(18, 2), default=0)
    spent_amount = Column(Numeric(18, 2), default=0)
    available_amount = Column(Numeric(18, 2), default=0)
    currency = Column(String(10), default="INR")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    cost_center = relationship("CostCenter", back_populates="budgets")
    gl_code = relationship("GLCode")

    __table_args__ = (
        UniqueConstraint("cost_center_id", "gl_code_id", "fiscal_year", "period", name="uq_budget"),
    )


# ─── DOCUMENT PROCESSING ──────────────────────────────────────────────────────

class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id = Column(String(30), unique=True, nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_extension = Column(String(10), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    mime_type = Column(String(100))
    checksum = Column(String(64))
    original_path = Column(String(500))
    ocr_path = Column(String(500))
    extracted_path = Column(String(500))
    final_path = Column(String(500))
    exception_path = Column(String(500))
    status = Column(String(30), default=DocumentStatus.PENDING, nullable=False, index=True)
    doc_type = Column(String(20))
    business_profile = Column(String(50), index=True)
    ai_profile_confidence = Column(Numeric(5, 4))
    ai_profile_reasoning = Column(Text)
    vendor_id = Column(UUID(as_uuid=False), ForeignKey("vendors.id"))
    po_id = Column(UUID(as_uuid=False), ForeignKey("purchase_orders.id"))
    grn_id = Column(UUID(as_uuid=False), ForeignKey("grns.id"))
    contract_id = Column(UUID(as_uuid=False), ForeignKey("contracts.id"))
    employee_id = Column(UUID(as_uuid=False), ForeignKey("employees.id"))
    invoice_number = Column(String(100), index=True)
    invoice_date = Column(Date)
    invoice_amount = Column(Numeric(18, 2))
    tax_amount = Column(Numeric(18, 2))
    total_amount = Column(Numeric(18, 2))
    currency = Column(String(10), default="INR")
    extracted_data = Column(JSON)
    ocr_text = Column(Text)
    ocr_confidence = Column(Numeric(5, 4))
    image_quality_report = Column(JSON)
    ingestion_source = Column(String(50), default="PORTAL")
    uploaded_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    processing_started_at = Column(DateTime(timezone=True))
    processing_completed_at = Column(DateTime(timezone=True))
    # Phase 6 additions (nullable — backward compatible)
    tenant_id = Column(String(100), default="default", index=True)
    workflow_state_id = Column(UUID(as_uuid=False))   # LangGraph thread_id soft reference
    overall_confidence_score = Column(Numeric(5, 4))
    processing_graph = Column(String(50))             # Which LangGraph graph ran
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    uploader = relationship("User", back_populates="documents", foreign_keys=[uploaded_by])
    vendor = relationship("Vendor", back_populates="documents")
    purchase_order = relationship("PurchaseOrder", back_populates="documents")
    grn = relationship("GRN", back_populates="documents")
    contract = relationship("Contract", back_populates="documents")
    employee = relationship("Employee", back_populates="documents")
    line_items = relationship("DocumentLineItem", back_populates="document", cascade="all, delete-orphan")
    workflow_state = relationship("WorkflowState", back_populates="document", uselist=False)
    validation_results = relationship("ValidationResult", back_populates="document", cascade="all, delete-orphan")
    matching_result = relationship("MatchingResult", back_populates="document", uselist=False)
    exceptions = relationship("Exception", back_populates="document", cascade="all, delete-orphan")
    approvals = relationship("Approval", back_populates="document", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="document")
    erp_posting = relationship("ERPPosting", back_populates="document", uselist=False)
    payment_schedule = relationship("PaymentSchedule", back_populates="document", uselist=False)

    __table_args__ = (
        Index("ix_documents_status_created", "status", "created_at"),
        Index("ix_documents_vendor_status", "vendor_id", "status"),
    )


class DocumentLineItem(Base):
    __tablename__ = "document_line_items"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    line_number = Column(Integer, nullable=False)
    item_code = Column(String(50))
    description = Column(Text)
    hsn_sac_code = Column(String(10))
    quantity = Column(Numeric(18, 4))
    unit_price = Column(Numeric(18, 4))
    uom = Column(String(20))
    discount_amount = Column(Numeric(18, 2), default=0)
    cgst_rate = Column(Numeric(5, 2), default=0)
    sgst_rate = Column(Numeric(5, 2), default=0)
    igst_rate = Column(Numeric(5, 2), default=0)
    cgst_amount = Column(Numeric(18, 2), default=0)
    sgst_amount = Column(Numeric(18, 2), default=0)
    igst_amount = Column(Numeric(18, 2), default=0)
    total_amount = Column(Numeric(18, 2))
    po_line_id = Column(UUID(as_uuid=False), ForeignKey("po_line_items.id"))
    gl_code = Column(String(20))
    cost_center = Column(String(50))

    document = relationship("Document", back_populates="line_items")
    matched_po_line = relationship("POLineItem")


class WorkflowState(Base):
    __tablename__ = "workflow_states"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True)
    current_stage = Column(String(50), nullable=False, default=ProcessingStage.INTAKE)
    current_agent = Column(String(50))
    progress_percent = Column(Integer, default=0)
    error_message = Column(Text)
    stage_history = Column(JSON, default=list)
    retry_count = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    document = relationship("Document", back_populates="workflow_state")


# ─── VALIDATION ──────────────────────────────────────────────────────────────

class ValidationProfile(Base):
    __tablename__ = "validation_profiles"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    name = Column(String(100), nullable=False)
    business_profile = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    rules = relationship("ValidationRule", back_populates="profile", cascade="all, delete-orphan")


class ValidationRule(Base):
    __tablename__ = "validation_rules"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    profile_id = Column(UUID(as_uuid=False), ForeignKey("validation_profiles.id", ondelete="CASCADE"), nullable=False)
    rule_code = Column(String(50), nullable=False)
    rule_name = Column(String(255), nullable=False)
    rule_type = Column(String(30), nullable=False)
    severity = Column(String(10), default="FAIL")
    parameters = Column(JSON, default=dict)
    error_message = Column(Text)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

    profile = relationship("ValidationProfile", back_populates="rules")

    __table_args__ = (
        UniqueConstraint("profile_id", "rule_code", name="uq_validation_rule"),
    )


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    rule_id = Column(UUID(as_uuid=False), ForeignKey("validation_rules.id"))
    rule_code = Column(String(50), nullable=False)
    rule_name = Column(String(255))
    status = Column(String(10), nullable=False)
    expected_value = Column(Text)
    actual_value = Column(Text)
    reason = Column(Text)
    severity = Column(String(10))
    agent = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    document = relationship("Document", back_populates="validation_results")
    rule = relationship("ValidationRule")

    __table_args__ = (
        Index("ix_validation_results_doc_status", "document_id", "status"),
    )


# ─── MATCHING ────────────────────────────────────────────────────────────────

class MatchingResult(Base):
    __tablename__ = "matching_results"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True)
    po_id = Column(UUID(as_uuid=False), ForeignKey("purchase_orders.id"))
    grn_id = Column(UUID(as_uuid=False), ForeignKey("grns.id"))
    match_status = Column(String(30), nullable=False)
    overall_match_score = Column(Numeric(5, 4), default=0)
    quantity_match = Column(Boolean)
    price_match = Column(Boolean)
    tax_match = Column(Boolean)
    total_match = Column(Boolean)
    vendor_match = Column(Boolean)
    variance_report = Column(JSON)
    line_matches = Column(JSON)
    tolerance_applied = Column(Boolean, default=False)
    matching_notes = Column(Text)
    matched_by = Column(String(50), default="MATCHING_AGENT")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    document = relationship("Document", back_populates="matching_result")
    purchase_order = relationship("PurchaseOrder")
    grn = relationship("GRN")


# ─── EXCEPTIONS ──────────────────────────────────────────────────────────────

class Exception(Base):
    __tablename__ = "exceptions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    exception_code = Column(String(50), nullable=False)
    exception_type = Column(String(100), nullable=False)
    severity = Column(String(20), nullable=False, default=ExceptionSeverity.MEDIUM)
    queue = Column(String(30), nullable=False, default=ExceptionQueue.AP_TEAM)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    agent_raised_by = Column(String(50))
    assigned_to = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    status = Column(String(20), default=ExceptionStatus.OPEN, nullable=False, index=True)
    sla_hours = Column(Integer, default=4)
    sla_deadline = Column(DateTime(timezone=True))
    resolution_notes = Column(Text)
    resolved_by = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    resolved_at = Column(DateTime(timezone=True))
    escalation_count = Column(Integer, default=0)
    escalated_to = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    escalated_at = Column(DateTime(timezone=True))
    resolution_type = Column(String(50))        # Phase 6: AUTO_FIX | MANUAL_FIX | OVERRIDE | REJECT
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    document = relationship("Document", back_populates="exceptions")
    assignee = relationship("User", foreign_keys=[assigned_to])
    resolver = relationship("User", foreign_keys=[resolved_by])
    escalated_to_user = relationship("User", foreign_keys=[escalated_to])

    __table_args__ = (
        Index("ix_exceptions_queue_status", "queue", "status"),
    )


# ─── APPROVALS ───────────────────────────────────────────────────────────────

class ApprovalRule(Base):
    __tablename__ = "approval_rules"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    name = Column(String(255), nullable=False)
    business_profile = Column(String(50))
    amount_min = Column(Numeric(18, 2), default=0)
    amount_max = Column(Numeric(18, 2))
    conditions = Column(JSON, default=dict)
    approval_matrix = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Approval(Base):
    __tablename__ = "approvals"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    approval_rule_id = Column(UUID(as_uuid=False), ForeignKey("approval_rules.id"))
    approval_level = Column(Integer, nullable=False, default=1)
    approver_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    delegate_id = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    status = Column(String(20), default=ApprovalStatus.PENDING, nullable=False, index=True)
    action = Column(String(20))
    comments = Column(Text)
    actioned_at = Column(DateTime(timezone=True))
    deadline = Column(DateTime(timezone=True))
    reminder_count = Column(Integer, default=0)
    last_reminder_at = Column(DateTime(timezone=True))
    authority_amount = Column(Numeric(18, 2))   # Phase 6: amount authorised at this level
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    document = relationship("Document", back_populates="approvals")
    approver = relationship("User", back_populates="approvals", foreign_keys=[approver_id])
    delegate = relationship("User", foreign_keys=[delegate_id])
    rule = relationship("ApprovalRule")

    __table_args__ = (
        Index("ix_approvals_approver_status", "approver_id", "status"),
    )


# ─── AUDIT & NOTIFICATIONS ────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id"), index=True)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(50))
    action = Column(String(100), nullable=False)
    agent = Column(String(50))
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    ip_address = Column(String(45))
    before_state = Column(JSON)
    after_state = Column(JSON)
    log_metadata = Column(JSON, default=dict)
    stage = Column(String(50))
    event_chain_hash = Column(String(64))       # Phase 6: running tamper-detection hash
    workflow_status = Column(String(50))        # Phase 6: workflow status at time of event
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    document = relationship("Document", back_populates="audit_logs")
    user = relationship("User", back_populates="audit_logs", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_audit_logs_doc_timestamp", "document_id", "timestamp"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id"))
    notification_type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text)
    action_url = Column(String(500))
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    user = relationship("User", back_populates="notifications")
    document = relationship("Document")


# ─── PAYMENT & ERP ───────────────────────────────────────────────────────────

class PaymentSchedule(Base):
    __tablename__ = "payment_schedules"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True)
    vendor_id = Column(UUID(as_uuid=False), ForeignKey("vendors.id"), nullable=True)
    invoice_amount = Column(Numeric(18, 2), nullable=False)
    tax_amount = Column(Numeric(18, 2), default=0)
    tds_deduction = Column(Numeric(18, 2), default=0)
    other_deductions = Column(Numeric(18, 2), default=0)
    net_payable = Column(Numeric(18, 2), nullable=False)
    payment_terms = Column(String(20), nullable=False)
    invoice_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    status = Column(String(20), default=PaymentStatus.SCHEDULED, nullable=False, index=True)
    payment_mode = Column(String(30))
    payment_reference = Column(String(100))
    bank_account = Column(String(50))
    bank_ifsc = Column(String(20))
    paid_amount = Column(Numeric(18, 2))
    paid_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    document = relationship("Document", back_populates="payment_schedule")
    vendor = relationship("Vendor", back_populates="payment_schedules")


class ERPPosting(Base):
    __tablename__ = "erp_postings"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True)
    posting_date = Column(Date, nullable=False)
    fiscal_year = Column(String(10))
    fiscal_period = Column(String(10))
    journal_entries = Column(JSON, nullable=False)
    erp_reference = Column(String(100))
    erp_system = Column(String(20), default=ERPSystem.MOCK, nullable=False)
    posting_status = Column(String(20), default="PENDING", nullable=False)
    error_message = Column(Text)
    payload = Column(JSON)
    posted_by = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    reversal_id = Column(UUID(as_uuid=False))
    reversal_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    document = relationship("Document", back_populates="erp_posting")
    posted_by_user = relationship("User", foreign_keys=[posted_by])


class Configuration(Base):
    __tablename__ = "configurations"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    category = Column(String(50), nullable=False)
    description = Column(Text)
    value_type = Column(String(20), default="STRING")
    is_active = Column(Boolean, default=True)
    is_encrypted = Column(Boolean, default=False)
    updated_by = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    updated_by_user = relationship("User", foreign_keys=[updated_by])


# ─── PHASE 6: NEW PLATFORM TABLES ─────────────────────────────────────────────

class WorkflowStateArchive(Base):
    """Long-term serialised WorkflowState after workflow completion (Phase 6)."""
    __tablename__ = "workflow_state_archive"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id"), nullable=False)
    tenant_id = Column(String(100), nullable=False, default="default")
    workflow_status = Column(String(50), nullable=False)
    processing_graph = Column(String(50))
    state_json = Column(Text, nullable=False)   # Full WorkflowState JSON
    archived_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_workflow_state_archive_doc", "document_id"),
    )


class WorkflowTimeline(Base):
    """Ordered agent execution events for UI timeline display (Phase 6)."""
    __tablename__ = "workflow_timelines"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id"), nullable=False)
    tenant_id = Column(String(100), nullable=False, default="default")
    node_name = Column(String(100), nullable=False)
    agent_name = Column(String(100))
    event_type = Column(String(50), nullable=False)  # NODE_ENTER | NODE_EXIT | INTERRUPT | RESUME
    status = Column(String(50))                       # SUCCESS | FAILED | INTERRUPTED
    duration_ms = Column(Integer)
    payload = Column(JSON, default=dict)
    occurred_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_workflow_timelines_doc_time", "document_id", "occurred_at"),
    )


class NotificationLog(Base):
    """Notification delivery history per document event (Phase 6)."""
    __tablename__ = "notification_logs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id"))
    tenant_id = Column(String(100), nullable=False, default="default")
    event_type = Column(String(100), nullable=False)
    channel = Column(String(50), nullable=False)    # EMAIL | TEAMS | SMS | WEBHOOK
    recipient = Column(String(255))
    template_id = Column(String(100))
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING | SENT | FAILED
    error_message = Column(Text)
    sent_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_notification_logs_doc", "document_id"),
        Index("ix_notification_logs_status", "status"),
    )


class RetryLog(Base):
    """Retry attempt history per operation (Phase 6)."""
    __tablename__ = "retry_logs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id"))
    tenant_id = Column(String(100), nullable=False, default="default")
    failed_agent = Column(String(100), nullable=False)
    attempt_number = Column(Integer, nullable=False, default=1)
    backoff_seconds = Column(Integer)
    error_code = Column(String(100))
    error_message = Column(Text)
    escalated = Column(Boolean, default=False)
    attempted_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_retry_logs_doc", "document_id"),
    )


class ExceptionResolutionHistory(Base):
    """Full resolution audit trail for exceptions (Phase 6)."""
    __tablename__ = "exception_resolution_history"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    exception_id = Column(UUID(as_uuid=False), ForeignKey("exceptions.id"), nullable=False)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id"), nullable=False)
    tenant_id = Column(String(100), nullable=False, default="default")
    resolution_type = Column(String(50), nullable=False)  # AUTO_FIX | MANUAL_FIX | OVERRIDE | REJECT
    resolution_notes = Column(Text)
    resolved_by = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    corrected_fields = Column(JSON, default=dict)
    resolved_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_exc_resolution_history_exc", "exception_id"),
        Index("ix_exc_resolution_history_doc", "document_id"),
    )


class FeatureFlag(Base):
    """Per-tenant feature flag overrides (Phase 6 — full implementation Phase 7)."""
    __tablename__ = "feature_flags"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    tenant_id = Column(String(100), nullable=False, default="default")
    flag_name = Column(String(100), nullable=False)
    is_enabled = Column(Boolean, nullable=False, default=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "flag_name", name="uq_feature_flag_tenant_name"),
        Index("ix_feature_flags_tenant", "tenant_id"),
    )


class PromptVersion(Base):
    """Versioned prompt history — one row per (tenant, prompt_name, version) (Phase 6)."""
    __tablename__ = "prompt_versions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    tenant_id = Column(String(100), nullable=False, default="default")
    prompt_name = Column(String(100), nullable=False)
    version = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, nullable=False, default=False)
    created_by = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    activated_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "prompt_name", "version", name="uq_prompt_version"),
        Index("ix_prompt_versions_tenant_name", "tenant_id", "prompt_name"),
    )


class TokenUsage(Base):
    """Per-tenant LLM token consumption tracking (Phase 6)."""
    __tablename__ = "token_usage"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    tenant_id = Column(String(100), nullable=False, default="default")
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id"))
    agent_name = Column(String(100))
    model = Column(String(100))
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost_usd = Column(Numeric(10, 6), default=0)
    recorded_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_token_usage_tenant", "tenant_id"),
        Index("ix_token_usage_doc", "document_id"),
    )
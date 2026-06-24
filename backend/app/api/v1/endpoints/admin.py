from __future__ import annotations

import json
import decimal
import datetime
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_async_session
from app.core.security import get_current_user
from app.models.models import (
    ApprovalRule, Asset, Budget, Configuration, CostCenter, Employee,
    GLCode, LeaseContract, Contract, User, UserRole,
    ValidationProfile, ValidationRule,
)
from app.schemas.schemas import (
    ApprovalRuleCreate, ApprovalRuleOut, AssetCreate, AssetOut,
    BudgetCreate, BudgetOut, ConfigurationOut, ConfigurationUpdate,
    ContractCreate, ContractOut, CostCenterCreate, CostCenterOut,
    EmployeeCreate, EmployeeOut, GLCodeCreate, GLCodeOut,
    LeaseContractCreate, LeaseContractOut,
    ValidationProfileCreate, ValidationProfileOut,
)

router = APIRouter(prefix="/admin", tags=["Admin / ERP Master"])


def _require_admin(current_user: User = Depends(get_current_user)):
    if current_user.role not in (UserRole.ADMIN, UserRole.FINANCE):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ── Cost Centers ──────────────────────────────────────────────────────────────

@router.get("/cost-centers", response_model=List[CostCenterOut])
async def list_cost_centers(db: AsyncSession = Depends(get_async_session), _=Depends(get_current_user)):
    result = await db.execute(select(CostCenter).where(CostCenter.is_active == True))
    return [CostCenterOut.model_validate(cc) for cc in result.scalars().all()]


@router.post("/cost-centers", response_model=CostCenterOut, status_code=201)
async def create_cost_center(body: CostCenterCreate, db: AsyncSession = Depends(get_async_session), _=Depends(_require_admin)):
    cc = CostCenter(**body.model_dump())
    db.add(cc)
    await db.flush()
    return CostCenterOut.model_validate(cc)


# ── GL Codes ──────────────────────────────────────────────────────────────────

@router.get("/gl-codes", response_model=List[GLCodeOut])
async def list_gl_codes(db: AsyncSession = Depends(get_async_session), _=Depends(get_current_user)):
    result = await db.execute(select(GLCode).where(GLCode.is_active == True))
    return [GLCodeOut.model_validate(gl) for gl in result.scalars().all()]


@router.post("/gl-codes", response_model=GLCodeOut, status_code=201)
async def create_gl_code(body: GLCodeCreate, db: AsyncSession = Depends(get_async_session), _=Depends(_require_admin)):
    gl = GLCode(**body.model_dump())
    db.add(gl)
    await db.flush()
    return GLCodeOut.model_validate(gl)


# ── Contracts ─────────────────────────────────────────────────────────────────

@router.get("/contracts", response_model=List[ContractOut])
async def list_contracts(db: AsyncSession = Depends(get_async_session), _=Depends(get_current_user)):
    result = await db.execute(select(Contract).options(selectinload(Contract.vendor)))
    contracts = result.scalars().all()
    return [ContractOut(id=str(c.id), contract_number=c.contract_number, vendor_id=str(c.vendor_id), vendor_name=c.vendor.name if c.vendor else None, contract_type=c.contract_type, title=c.title, start_date=c.start_date, end_date=c.end_date, value=c.value, currency=c.currency, status=c.status, created_at=c.created_at) for c in contracts]


@router.post("/contracts", response_model=ContractOut, status_code=201)
async def create_contract(body: ContractCreate, db: AsyncSession = Depends(get_async_session), _=Depends(_require_admin)):
    contract = Contract(**body.model_dump(), created_by=None)
    db.add(contract)
    await db.flush()
    return ContractOut(id=str(contract.id), contract_number=contract.contract_number, vendor_id=str(contract.vendor_id), vendor_name=None, contract_type=contract.contract_type, title=contract.title, start_date=contract.start_date, end_date=contract.end_date, value=contract.value, currency=contract.currency, status=contract.status, created_at=contract.created_at)


# ── Lease Contracts ───────────────────────────────────────────────────────────

@router.get("/lease-contracts", response_model=List[LeaseContractOut])
async def list_lease_contracts(db: AsyncSession = Depends(get_async_session), _=Depends(get_current_user)):
    result = await db.execute(select(LeaseContract).options(selectinload(LeaseContract.vendor)))
    leases = result.scalars().all()
    return [LeaseContractOut(id=str(l.id), contract_number=l.contract_number, vendor_id=str(l.vendor_id), vendor_name=l.vendor.name if l.vendor else None, property_name=l.property_name, property_address=l.property_address, monthly_rent=l.monthly_rent, lease_start=l.lease_start, lease_end=l.lease_end, gst_applicable=l.gst_applicable, gst_rate=l.gst_rate, tds_rate=l.tds_rate, status=l.status) for l in leases]


@router.post("/lease-contracts", response_model=LeaseContractOut, status_code=201)
async def create_lease_contract(body: LeaseContractCreate, db: AsyncSession = Depends(get_async_session), _=Depends(_require_admin)):
    lease = LeaseContract(**body.model_dump())
    db.add(lease)
    await db.flush()
    return LeaseContractOut(id=str(lease.id), contract_number=lease.contract_number, vendor_id=str(lease.vendor_id), vendor_name=None, property_name=lease.property_name, property_address=lease.property_address, monthly_rent=lease.monthly_rent, lease_start=lease.lease_start, lease_end=lease.lease_end, gst_applicable=lease.gst_applicable, gst_rate=lease.gst_rate, tds_rate=lease.tds_rate, status=lease.status)


# ── Assets ────────────────────────────────────────────────────────────────────

@router.get("/assets", response_model=List[AssetOut])
async def list_assets(db: AsyncSession = Depends(get_async_session), _=Depends(get_current_user)):
    result = await db.execute(select(Asset).options(selectinload(Asset.vendor)))
    assets = result.scalars().all()
    return [AssetOut(id=str(a.id), asset_code=a.asset_code, name=a.name, category=a.category, serial_number=a.serial_number, vendor_id=str(a.vendor_id) if a.vendor_id else None, vendor_name=a.vendor.name if a.vendor else None, purchase_date=a.purchase_date, purchase_value=a.purchase_value, current_value=a.current_value, location=a.location, status=a.status, capitalized=a.capitalized, created_at=a.created_at) for a in assets]


@router.post("/assets", response_model=AssetOut, status_code=201)
async def create_asset(body: AssetCreate, db: AsyncSession = Depends(get_async_session), _=Depends(_require_admin)):
    asset = Asset(**body.model_dump())
    db.add(asset)
    await db.flush()
    return AssetOut(id=str(asset.id), asset_code=asset.asset_code, name=asset.name, category=asset.category, serial_number=asset.serial_number, vendor_id=str(asset.vendor_id) if asset.vendor_id else None, vendor_name=None, purchase_date=asset.purchase_date, purchase_value=asset.purchase_value, current_value=asset.current_value, location=asset.location, status=asset.status, capitalized=asset.capitalized, created_at=asset.created_at)


# ── Employees ─────────────────────────────────────────────────────────────────

@router.get("/employees", response_model=List[EmployeeOut])
async def list_employees(db: AsyncSession = Depends(get_async_session), _=Depends(get_current_user)):
    result = await db.execute(select(Employee).where(Employee.is_active == True))
    return [EmployeeOut.model_validate(e) for e in result.scalars().all()]


@router.post("/employees", response_model=EmployeeOut, status_code=201)
async def create_employee(body: EmployeeCreate, db: AsyncSession = Depends(get_async_session), _=Depends(_require_admin)):
    emp = Employee(**body.model_dump())
    db.add(emp)
    await db.flush()
    return EmployeeOut.model_validate(emp)


# ── Budgets ───────────────────────────────────────────────────────────────────

@router.get("/budgets", response_model=List[BudgetOut])
async def list_budgets(db: AsyncSession = Depends(get_async_session), _=Depends(get_current_user)):
    result = await db.execute(select(Budget).options(selectinload(Budget.cost_center), selectinload(Budget.gl_code)))
    budgets = result.scalars().all()
    return [BudgetOut(id=str(b.id), cost_center_id=str(b.cost_center_id), cost_center_name=b.cost_center.name if b.cost_center else None, gl_code_id=str(b.gl_code_id), gl_code_name=b.gl_code.name if b.gl_code else None, fiscal_year=b.fiscal_year, period=b.period, total_amount=b.total_amount, committed_amount=b.committed_amount, spent_amount=b.spent_amount, available_amount=b.available_amount, currency=b.currency) for b in budgets]


@router.post("/budgets", response_model=BudgetOut, status_code=201)
async def create_budget(body: BudgetCreate, db: AsyncSession = Depends(get_async_session), _=Depends(_require_admin)):
    budget = Budget(**body.model_dump(), committed_amount=0, spent_amount=0, available_amount=body.total_amount)
    db.add(budget)
    await db.flush()
    return BudgetOut(id=str(budget.id), cost_center_id=str(budget.cost_center_id), cost_center_name=None, gl_code_id=str(budget.gl_code_id), gl_code_name=None, fiscal_year=budget.fiscal_year, period=budget.period, total_amount=budget.total_amount, committed_amount=budget.committed_amount, spent_amount=budget.spent_amount, available_amount=budget.available_amount, currency=budget.currency)


# ── Approval Rules ────────────────────────────────────────────────────────────

@router.get("/approval-rules", response_model=List[ApprovalRuleOut])
async def list_approval_rules(db: AsyncSession = Depends(get_async_session), _=Depends(get_current_user)):
    result = await db.execute(select(ApprovalRule).where(ApprovalRule.is_active == True))
    return [ApprovalRuleOut.model_validate(r) for r in result.scalars().all()]


@router.post("/approval-rules", response_model=ApprovalRuleOut, status_code=201)
async def create_approval_rule(body: ApprovalRuleCreate, db: AsyncSession = Depends(get_async_session), _=Depends(_require_admin)):
    rule = ApprovalRule(**body.model_dump())
    db.add(rule)
    await db.flush()
    return ApprovalRuleOut.model_validate(rule)


# ── Validation Profiles ───────────────────────────────────────────────────────

@router.get("/validation-profiles", response_model=List[ValidationProfileOut])
async def list_validation_profiles(db: AsyncSession = Depends(get_async_session), _=Depends(get_current_user)):
    result = await db.execute(select(ValidationProfile).options(selectinload(ValidationProfile.rules)))
    return [ValidationProfileOut.model_validate(p) for p in result.scalars().all()]


@router.post("/validation-profiles", response_model=ValidationProfileOut, status_code=201)
async def create_validation_profile(body: ValidationProfileCreate, db: AsyncSession = Depends(get_async_session), _=Depends(_require_admin)):
    profile = ValidationProfile(name=body.name, business_profile=body.business_profile, description=body.description)
    db.add(profile)
    await db.flush()
    for rule_data in body.rules:
        rule = ValidationRule(profile_id=profile.id, **rule_data.model_dump())
        db.add(rule)
    await db.flush()
    result = await db.execute(select(ValidationProfile).options(selectinload(ValidationProfile.rules)).where(ValidationProfile.id == profile.id))
    return ValidationProfileOut.model_validate(result.scalar_one())


# ── Configurations ────────────────────────────────────────────────────────────

@router.get("/configurations", response_model=List[ConfigurationOut])
async def list_configurations(db: AsyncSession = Depends(get_async_session), _=Depends(_require_admin)):
    result = await db.execute(select(Configuration))
    return [ConfigurationOut.model_validate(c) for c in result.scalars().all()]


@router.patch("/configurations/{config_id}", response_model=ConfigurationOut)
async def update_configuration(config_id: str, body: ConfigurationUpdate, db: AsyncSession = Depends(get_async_session), current_user: User = Depends(_require_admin)):
    result = await db.execute(select(Configuration).where(Configuration.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")
    config.value = body.value
    if body.is_active is not None:
        config.is_active = body.is_active
    config.updated_by = str(current_user.id)
    await db.flush()
    return ConfigurationOut.model_validate(config)


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(db: AsyncSession = Depends(get_async_session), _=Depends(_require_admin)):
    from app.schemas.schemas import UserOut
    result = await db.execute(select(User).where(User.is_active == True))
    return [UserOut.model_validate(u) for u in result.scalars().all()]


# ── GRNs ─────────────────────────────────────────────────────────────────────

@router.get("/grns")
async def list_grns(db: AsyncSession = Depends(get_async_session), _=Depends(get_current_user)):
    from app.models.models import GRN, GRNLineItem, PurchaseOrder, Vendor
    result = await db.execute(
        select(GRN)
        .options(
            selectinload(GRN.purchase_order),
            selectinload(GRN.vendor),
            selectinload(GRN.line_items),
        )
        .order_by(GRN.received_date.desc())
        .limit(200)
    )
    grns = result.scalars().all()
    return [
        {
            "id": str(g.id),
            "grn_number": g.grn_number,
            "po_number": g.purchase_order.po_number if g.purchase_order else None,
            "vendor_name": g.vendor.name if g.vendor else None,
            "vendor_code": g.vendor.vendor_code if g.vendor else None,
            "received_date": g.received_date.isoformat() if g.received_date else None,
            "status": g.status,
            "quality_check_passed": g.quality_check_passed,
            "warehouse_location": g.warehouse_location,
            "remarks": g.remarks,
            "line_items_count": len(g.line_items),
            "total_accepted_qty": float(
                sum(li.accepted_quantity or 0 for li in g.line_items)
            ),
        }
        for g in grns
    ]


@router.get("/po-line-items/{po_id}")
async def list_po_line_items(po_id: str, db: AsyncSession = Depends(get_async_session), _=Depends(get_current_user)):
    from app.models.models import POLineItem
    result = await db.execute(
        select(POLineItem).where(POLineItem.po_id == po_id).order_by(POLineItem.line_number)
    )
    items = result.scalars().all()
    return [
        {
            "id": str(li.id),
            "line_number": li.line_number,
            "description": li.description,
            "quantity": float(li.quantity or 0),
            "unit_price": float(li.unit_price or 0),
            "uom": li.uom,
            "total_amount": float(li.total_amount or 0),
            "cgst_rate": float(li.cgst_rate or 0),
            "sgst_rate": float(li.sgst_rate or 0),
            "igst_rate": float(li.igst_rate or 0),
        }
        for li in items
    ]


# ── ERP Postings (completed) ────────────────────────────────────────────────

@router.get("/erp-postings")
async def list_erp_postings(db: AsyncSession = Depends(get_async_session), _=Depends(get_current_user)):
    from app.models.models import ERPPosting, Document
    result = await db.execute(
        select(ERPPosting, Document)
        .join(Document, Document.id == ERPPosting.document_id)
        .order_by(desc(ERPPosting.created_at))
        .limit(200)
    )
    rows = result.all()
    return [
        {
            "id": str(p.id),
            "document_id": str(p.document_id),
            "document_ref": d.document_id,
            "invoice_number": d.invoice_number,
            "business_profile": d.business_profile,
            "erp_reference": p.erp_reference,
            "erp_system": p.erp_system,
            "posting_status": p.posting_status,
            "posting_date": p.posting_date.isoformat() if p.posting_date else None,
            "fiscal_period": p.fiscal_period,
            "journal_entries": p.journal_entries,
            "total_amount": float(d.total_amount or 0),
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p, d in rows
    ]


@router.get("/payment-schedules")
async def list_payment_schedules(db: AsyncSession = Depends(get_async_session), _=Depends(get_current_user)):
    from app.models.models import PaymentSchedule, Document
    result = await db.execute(
        select(PaymentSchedule, Document)
        .join(Document, Document.id == PaymentSchedule.document_id)
        .order_by(desc(PaymentSchedule.created_at))
        .limit(200)
    )
    rows = result.all()
    return [
        {
            "id": str(ps.id),
            "document_ref": d.document_id,
            "invoice_number": d.invoice_number,
            "net_payable": float(ps.net_payable or 0),
            "tds_deduction": float(ps.tds_deduction or 0),
            "payment_terms": ps.payment_terms,
            "due_date": ps.due_date.isoformat() if ps.due_date else None,
            "status": ps.status,
        }
        for ps, d in rows
    ]


# ── Postgres DB Browser ───────────────────────────────────────────────────────
# Read-only table explorer. Only app-owned tables are exposed (whitelist).

_ALLOWED_TABLES = {
    "vendors", "vendor_contacts",
    "purchase_orders", "po_line_items",
    "grns", "grn_line_items",
    "documents", "document_line_items",
    "matching_results", "validation_results",
    "workflow_states", "erp_postings", "payment_schedules",
    "users", "employees", "contracts", "lease_contracts",
    "assets", "cost_centers", "gl_codes", "budgets",
    "approvals", "exceptions", "audit_logs", "notifications",
    "configurations", "approval_rules", "approval_rule_steps",
    "validation_profiles", "validation_rules",
    "document_classifications", "blanket_po_drawdowns",
}


def _serialize(value: Any) -> Any:
    """Make any DB value JSON-safe."""
    if value is None:
        return None
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (dict, list)):
        return value
    return str(value)


@router.get("/db/tables")
async def db_list_tables(
    db: AsyncSession = Depends(get_async_session),
    _=Depends(_require_admin),
):
    """List all app tables with approximate row counts."""
    result = await db.execute(text("""
        SELECT
            t.table_name,
            COALESCE(s.n_live_tup, 0)::bigint AS row_count
        FROM information_schema.tables t
        LEFT JOIN pg_stat_user_tables s ON s.relname = t.table_name
        WHERE t.table_schema = 'public'
          AND t.table_type = 'BASE TABLE'
        ORDER BY t.table_name
    """))
    rows = result.fetchall()
    return [
        {"table_name": r[0], "row_count": int(r[1])}
        for r in rows
        if r[0] in _ALLOWED_TABLES
    ]


@router.get("/db/tables/{table_name}/schema")
async def db_table_schema(
    table_name: str,
    db: AsyncSession = Depends(get_async_session),
    _=Depends(_require_admin),
):
    """Return column definitions for a table."""
    if table_name not in _ALLOWED_TABLES:
        raise HTTPException(status_code=400, detail="Table not allowed")
    result = await db.execute(text("""
        SELECT
            column_name,
            data_type,
            character_maximum_length,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = :tbl
        ORDER BY ordinal_position
    """), {"tbl": table_name})
    return [
        {
            "name": r[0],
            "type": r[1],
            "max_length": r[2],
            "nullable": r[3] == "YES",
        }
        for r in result.fetchall()
    ]


@router.get("/db/tables/{table_name}/data")
async def db_table_data(
    table_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    _=Depends(_require_admin),
):
    """Return paginated rows for a table."""
    if table_name not in _ALLOWED_TABLES:
        raise HTTPException(status_code=400, detail="Table not allowed")

    offset = (page - 1) * page_size

    # Total count
    count_result = await db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))  # noqa: S608
    total = count_result.scalar() or 0

    # Determine order column — prefer created_at, else id, else first col
    col_result = await db.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :tbl
        ORDER BY ordinal_position
    """), {"tbl": table_name})
    cols = [r[0] for r in col_result.fetchall()]

    order_col = "created_at" if "created_at" in cols else ("id" if "id" in cols else cols[0])

    data_result = await db.execute(text(
        f'SELECT * FROM "{table_name}" ORDER BY "{order_col}" DESC NULLS LAST '  # noqa: S608
        f"LIMIT :lim OFFSET :off"
    ), {"lim": page_size, "off": offset})

    result_cols = list(data_result.keys())
    rows = data_result.fetchall()

    return {
        "table": table_name,
        "columns": result_cols,
        "rows": [
            {col: _serialize(val) for col, val in zip(result_cols, row)}
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }
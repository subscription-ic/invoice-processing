"""
Seed script: Creates all reference data for the AP Automation Platform.
Run: python seed/seed.py

Creates:
- 6 users (admin, ap team, finance, approvers, viewer)
- 20 vendors
- 20 purchase orders with line items
- 20 GRNs
- 10 service contracts
- 10 lease contracts
- 20 assets
- 20 employees
- Cost centers, GL codes, budgets
- Approval rules (4-tier matrix)
- Validation profiles for all 9 business profiles
- Configurations
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

# Resolve backend path:
#   Docker:  backend mounted at /app, seed at /seed
#   Dev:     backend at ../backend relative to seed/
_candidates = [
    "/app",                                              # Docker
    str(Path(__file__).parent.parent / "backend"),      # Local dev
]
for _candidate in _candidates:
    if Path(_candidate).exists() and Path(_candidate, "app", "core").exists():
        sys.path.insert(0, _candidate)
        break

from datetime import date, timedelta
from decimal import Decimal
import random

from sqlalchemy.orm import Session
from app.core.database import SyncSessionLocal
from app.core.security import hash_password
from app.models.models import (
    User, Vendor, VendorContact, CostCenter, GLCode,
    PurchaseOrder, POLineItem, GRN, GRNLineItem,
    Contract, LeaseContract, Asset, Employee, Budget,
    ApprovalRule, ValidationProfile, ValidationRule,
    Configuration, UserRole, POStatus, GRNStatus,
)

# Ensure seed/ directory is importable (handles docker exec and direct invocation)
_seed_dir = str(Path(__file__).parent)
if _seed_dir not in sys.path:
    sys.path.insert(0, _seed_dir)

from seed_erp_from_excel import (  # noqa: E402
    seed_vendors as seed_vendors_from_excel,
    seed_purchase_orders as seed_pos_from_excel,
    seed_grns as seed_grns_from_excel,
)


def seed_erp_from_excel(db: Session, users: list) -> tuple:
    """Seed vendors, POs, GRNs from Excel register files. Skips if data exists."""
    if db.query(Vendor).count() > 0:
        print("  ERP master data already exists — skipping Excel import.")
        vendor_map = {v.vendor_code: v for v in db.query(Vendor).all()}
        po_map = {p.po_number: p for p in db.query(PurchaseOrder).all()}
        return vendor_map, po_map

    admin_user = users[0]
    vendor_map = seed_vendors_from_excel(db)
    po_map = seed_pos_from_excel(db, vendor_map, admin_user)
    seed_grns_from_excel(db, vendor_map, po_map, admin_user)
    return vendor_map, po_map


def seed_all():
    db = SyncSessionLocal()
    try:
        print("🌱 Starting seed process...")

        gl_codes = seed_gl_codes(db)
        cost_centers = seed_cost_centers(db)
        users = seed_users(db)
        # Vendors, POs, GRNs come from the Excel register files
        vendor_map, po_map = seed_erp_from_excel(db, users)
        vendors = list(vendor_map.values())
        pos = list(po_map.values())
        employees = seed_employees(db, cost_centers, users)
        contracts = seed_contracts(db, vendors, cost_centers, gl_codes, users)
        leases = seed_lease_contracts(db, vendors, cost_centers, gl_codes)
        assets = seed_assets(db, vendors, cost_centers, gl_codes)
        seed_budgets(db, cost_centers, gl_codes)
        seed_approval_rules(db, users)
        seed_validation_profiles(db)
        seed_configurations(db)

        db.commit()
        print("✅ Seed complete!")
        print(f"   Users: {len(users)}")
        print(f"   Vendors: {len(vendors)}")
        print(f"   Purchase Orders: {len(pos)}")
        print(f"   Contracts: {len(contracts)}")
        print(f"   Lease Contracts: {len(leases)}")
        print(f"   Assets: {len(assets)}")
        print(f"   Employees: {len(employees)}")

    except Exception as e:
        db.rollback()
        print(f"❌ Seed failed: {e}")
        raise
    finally:
        db.close()


def seed_gl_codes(db: Session) -> list:
    if db.query(GLCode).count() > 0:
        print("GL codes already exist, skipping...")
        return db.query(GLCode).all()

    gl_data = [
        ("5001", "Raw Material Purchase", "EXPENSE", "COGS"),
        ("5002", "IT Equipment", "ASSET", "CAPEX"),
        ("5003", "Office Equipment", "ASSET", "CAPEX"),
        ("5004", "Machinery & Plant", "ASSET", "CAPEX"),
        ("5005", "Software Licenses", "EXPENSE", "OPEX"),
        ("5006", "IT Services", "EXPENSE", "OPEX"),
        ("5007", "Consulting Fees", "EXPENSE", "OPEX"),
        ("5008", "Office Rent", "EXPENSE", "OPEX"),
        ("5009", "Utilities", "EXPENSE", "OPEX"),
        ("5010", "Travel & Entertainment", "EXPENSE", "OPEX"),
        ("5011", "Employee Reimbursements", "EXPENSE", "OPEX"),
        ("5012", "Petty Cash Expenses", "EXPENSE", "OPEX"),
        ("5013", "Maintenance & Repairs", "EXPENSE", "OPEX"),
        ("1401", "Input GST Credit", "ASSET", "TAX"),
        ("2001", "Accounts Payable", "LIABILITY", "AP"),
        ("1001", "Cash & Bank", "ASSET", "CURRENT"),
        ("4001", "Sales Revenue", "REVENUE", "INCOME"),
        ("5014", "Transportation & Logistics", "EXPENSE", "OPEX"),
        ("5015", "Insurance Premium", "EXPENSE", "OPEX"),
        ("5016", "Professional Fees", "EXPENSE", "OPEX"),
    ]

    codes = []
    for code, name, category, sub_category in gl_data:
        gl = GLCode(code=code, name=name, category=category, sub_category=sub_category, account_type="PL" if category in ("EXPENSE", "REVENUE") else "BS")
        db.add(gl)
        codes.append(gl)
    db.flush()
    print(f"  ✓ {len(codes)} GL codes created")
    return codes


def seed_cost_centers(db: Session) -> list:
    if db.query(CostCenter).count() > 0:
        return db.query(CostCenter).all()

    data = [
        ("CC001", "Manufacturing", "Production"),
        ("CC002", "Information Technology", "IT"),
        ("CC003", "Finance & Accounts", "Finance"),
        ("CC004", "Human Resources", "HR"),
        ("CC005", "Sales & Marketing", "Sales"),
        ("CC006", "Research & Development", "R&D"),
        ("CC007", "Administration", "Admin"),
        ("CC008", "Logistics & Supply Chain", "Logistics"),
        ("CC009", "Quality Assurance", "QA"),
        ("CC010", "Customer Service", "CX"),
    ]
    centers = []
    for code, name, dept in data:
        cc = CostCenter(code=code, name=name, department=dept)
        db.add(cc)
        centers.append(cc)
    db.flush()
    print(f"  ✓ {len(centers)} cost centers created")
    return centers


def seed_users(db: Session) -> list:
    if db.query(User).count() > 0:
        return db.query(User).all()

    user_data = [
        ("admin@company.com", "System Admin", UserRole.ADMIN, "IT"),
        ("ap@company.com", "Priya Sharma", UserRole.AP_TEAM, "Finance"),
        ("finance@company.com", "Rajesh Kumar", UserRole.FINANCE, "Finance"),
        ("approver1@company.com", "Anita Singh", UserRole.APPROVER, "Operations"),
        ("approver2@company.com", "Vikram Mehta", UserRole.APPROVER, "Finance"),
        ("procurement@company.com", "Suresh Nair", UserRole.PROCUREMENT, "Supply Chain"),
        ("viewer@company.com", "Ravi Patel", UserRole.VIEWER, "IT"),
    ]
    users = []
    for email, name, role, dept in user_data:
        u = User(email=email, name=name, hashed_password=hash_password("password123"), role=role, department=dept)
        db.add(u)
        users.append(u)
    db.flush()
    print(f"  ✓ {len(users)} users created")
    return users


def seed_vendors(db: Session) -> list:
    if db.query(Vendor).count() > 0:
        return db.query(Vendor).all()

    vendor_data = [
        ("V001", "Tata Steel Ltd", "27AAACT2727Q1ZW", "AAACT2727Q", "GOODS", "MANUFACTURING", "Mumbai", "Maharashtra"),
        ("V002", "Infosys Technologies", "29AAACI1681G1ZW", "AAACI1681G", "SERVICES", "IT", "Bangalore", "Karnataka"),
        ("V003", "Reliance Industries", "27AAACR5055K1Z9", "AAACR5055K", "GOODS", "ENERGY", "Mumbai", "Maharashtra"),
        ("V004", "Wipro Limited", "29AAACW0454H1ZR", "AAACW0454H", "SERVICES", "IT", "Bangalore", "Karnataka"),
        ("V005", "Mahindra & Mahindra", "27AAACM3025E1ZE", "AAACM3025E", "GOODS", "AUTOMOTIVE", "Mumbai", "Maharashtra"),
        ("V006", "HCL Technologies", "09AAACH7099R1ZQ", "AAACH7099R", "SERVICES", "IT", "Noida", "Uttar Pradesh"),
        ("V007", "JSW Steel Ltd", "27AAACJ5765F1ZK", "AAACJ5765F", "GOODS", "MANUFACTURING", "Mumbai", "Maharashtra"),
        ("V008", "Tech Mahindra", "27AAACT8374B1ZM", "AAACT8374B", "SERVICES", "IT", "Pune", "Maharashtra"),
        ("V009", "Larsen & Toubro", "27AAACL8044L1ZC", "AAACL8044L", "BOTH", "ENGINEERING", "Mumbai", "Maharashtra"),
        ("V010", "HDFC Realty", "27AAACH4668K1ZU", "AAACH4668K", "SERVICES", "REAL_ESTATE", "Mumbai", "Maharashtra"),
        ("V011", "Asian Paints Ltd", "27AAACA3602H1ZA", "AAACA3602H", "GOODS", "CHEMICALS", "Mumbai", "Maharashtra"),
        ("V012", "Amazon Web Services", "07AAACD1234G1ZA", "AAACD1234G", "SERVICES", "CLOUD", "Delhi", "Delhi"),
        ("V013", "Office Depot India", "27AAACD9876F1ZB", "AAACD9876F", "GOODS", "STATIONERY", "Mumbai", "Maharashtra"),
        ("V014", "Siemens India", "27AAACS1234H1ZC", "AAACS1234H", "GOODS", "MACHINERY", "Mumbai", "Maharashtra"),
        ("V015", "Bajaj Electricals", "27AAACB1234J1ZD", "AAACB1234J", "GOODS", "ELECTRICAL", "Mumbai", "Maharashtra"),
        ("V016", "DHL Logistics", "27AAACD5678K1ZE", "AAACD5678K", "SERVICES", "LOGISTICS", "Mumbai", "Maharashtra"),
        ("V017", "Cipla Pharmaceuticals", "27AAACC1234L1ZF", "AAACC1234L", "GOODS", "PHARMA", "Mumbai", "Maharashtra"),
        ("V018", "KPMG Advisory", "07AAACK1234M1ZG", "AAACK1234M", "SERVICES", "CONSULTING", "Delhi", "Delhi"),
        ("V019", "Blue Dart Express", "07AAACD9999N1ZH", "AAACD9999N", "SERVICES", "COURIER", "Delhi", "Delhi"),
        ("V020", "Bharat Properties", "27AAACB5678P1ZI", "AAACB5678P", "SERVICES", "REAL_ESTATE", "Mumbai", "Maharashtra"),
    ]

    vendors = []
    for i, (code, name, gstin, pan, vtype, cat, city, state) in enumerate(vendor_data):
        v = Vendor(
            vendor_code=code, name=name, gstin=gstin, pan=pan,
            vendor_type=vtype, vendor_category=cat, city=city, state=state,
            country="India", payment_terms=random.choice(["NET30", "NET45", "NET60"]),
            bank_name=random.choice(["HDFC Bank", "SBI", "ICICI Bank", "Axis Bank"]),
            bank_account_number=f"1234{random.randint(100000, 999999)}",
            bank_ifsc=f"HDFC0{random.randint(10000, 99999)}",
            is_approved=True,
            credit_limit=Decimal(str(random.choice([500000, 1000000, 2000000, 5000000]))),
            tds_applicable=vtype == "SERVICES",
            tds_rate=Decimal("10") if vtype == "SERVICES" else Decimal("0"),
        )
        db.add(v)
        vendors.append(v)

        # Primary contact
        contact = VendorContact(
            vendor_id=v.id, name=f"Mr. {name.split()[0]} Contact",
            email=f"billing@{name.split()[0].lower()}.com",
            phone=f"+91-{random.randint(7000000000, 9999999999)}",
            designation="Accounts Manager", is_primary=True, contact_type="BILLING",
        )
        db.add(contact)

    db.flush()
    print(f"  ✓ {len(vendors)} vendors created")
    return vendors


def seed_purchase_orders(db: Session, vendors, cost_centers, gl_codes, users) -> tuple:
    if db.query(PurchaseOrder).count() > 0:
        pos = db.query(PurchaseOrder).all()
        lines = db.query(POLineItem).all()
        return pos, lines

    admin_user = users[0]
    approver = users[3]
    pos = []
    all_lines = []

    po_templates = [
        # (vendor_idx, description, category, unit, qty, price, gl_idx)
        (0, "Hot Rolled Steel Coils", "RAW_MATERIAL", "MT", 100, 52000, 0),
        (0, "Cold Rolled Steel Sheets", "RAW_MATERIAL", "MT", 50, 65000, 0),
        (4, "Engine Assembly Components", "RAW_MATERIAL", "EA", 500, 12000, 0),
        (6, "Structural Steel Beams", "RAW_MATERIAL", "MT", 75, 48000, 0),
        (10, "Industrial Paint - Epoxy", "RAW_MATERIAL", "LTR", 1000, 450, 0),
        (13, "CNC Turning Machine", "CAPEX_MACHINERY", "EA", 2, 850000, 3),
        (13, "Industrial Lathe Machine", "CAPEX_MACHINERY", "EA", 1, 1200000, 3),
        (14, "UPS Systems 20KVA", "CAPEX_ELECTRICAL", "EA", 5, 125000, 1),
        (1, "ERP Implementation Services", "OPEX_IT", "MON", 12, 500000, 5),
        (3, "Cloud Infrastructure Services", "OPEX_IT", "MON", 12, 200000, 5),
        (5, "IT Support Services", "OPEX_IT", "MON", 12, 150000, 5),
        (7, "Software Development", "OPEX_IT", "MON", 6, 800000, 5),
        (11, "AWS Cloud Services", "OPEX_IT", "MON", 12, 250000, 5),
        (17, "Management Consulting", "OPEX_CONSULTING", "MON", 3, 1500000, 6),
        (8, "Civil Construction Work", "CAPEX_CIVIL", "LS", 1, 5000000, 3),
        (15, "Freight Forwarding Services", "OPEX_LOGISTICS", "MON", 12, 180000, 13),
        (18, "Courier Services", "OPEX_LOGISTICS", "MON", 12, 50000, 13),
        (16, "API Raw Materials", "RAW_MATERIAL", "KG", 5000, 1200, 0),
        (12, "Office Stationery Supply", "OPEX_ADMIN", "MON", 6, 25000, 8),
        (2, "Chemical Feedstock", "RAW_MATERIAL", "MT", 200, 85000, 0),
    ]

    for i, (vi, desc, cat, uom, qty, price, gl_idx) in enumerate(po_templates):
        po_num = f"PO-2024-{str(i+1).zfill(4)}"
        vendor = vendors[vi]
        total = Decimal(str(qty * price))

        po = PurchaseOrder(
            po_number=po_num,
            vendor_id=vendor.id,
            status=POStatus.OPEN if i % 4 != 0 else POStatus.PARTIALLY_RECEIVED,
            total_amount=total,
            invoiced_amount=Decimal("0"),
            currency="INR",
            cost_center_id=cost_centers[i % len(cost_centers)].id,
            gl_code_id=gl_codes[gl_idx].id,
            payment_terms=vendor.payment_terms,
            po_date=date.today() - timedelta(days=random.randint(10, 90)),
            delivery_date=date.today() + timedelta(days=random.randint(7, 30)),
            created_by=str(admin_user.id),
            approved_by=str(approver.id),
        )
        db.add(po)
        db.flush()

        # Line items (1-3 per PO)
        for j in range(random.randint(1, 3)):
            line_qty = Decimal(str(qty // (j + 1)))
            line_price = Decimal(str(price))
            line_total = line_qty * line_price
            cgst = Decimal("9") if vendor.state == "Maharashtra" else Decimal("0")
            sgst = Decimal("9") if vendor.state == "Maharashtra" else Decimal("0")
            igst = Decimal("0") if vendor.state == "Maharashtra" else Decimal("18")

            li = POLineItem(
                po_id=po.id,
                line_number=j + 1,
                item_code=f"ITEM-{i+1:03d}-{j+1}",
                description=f"{desc} - Grade {chr(65+j)}",
                hsn_sac_code=f"{random.randint(2500, 9999)}",
                quantity=line_qty,
                received_quantity=Decimal("0"),
                invoiced_quantity=Decimal("0"),
                unit_price=line_price,
                uom=uom,
                total_amount=line_total,
                gl_code_id=gl_codes[gl_idx].id,
                cgst_rate=cgst,
                sgst_rate=sgst,
                igst_rate=igst,
            )
            db.add(li)
            all_lines.append(li)

        pos.append(po)

    db.flush()
    print(f"  ✓ {len(pos)} purchase orders created")
    return pos, all_lines


def seed_grns(db: Session, pos, po_lines, vendors, users) -> list:
    if db.query(GRN).count() > 0:
        return db.query(GRN).all()

    warehouse_user = users[0]
    grns = []

    # Create GRNs for first 20 POs (goods-related ones)
    goods_pos = [po for po in pos if po][:20]

    for i, po in enumerate(goods_pos):
        grn_num = f"GRN-2024-{str(i+1).zfill(4)}"
        grn = GRN(
            grn_number=grn_num,
            po_id=po.id,
            vendor_id=po.vendor_id,
            received_date=po.po_date + timedelta(days=random.randint(5, 20)),
            status=GRNStatus.ACCEPTED,
            received_by=str(warehouse_user.id),
            warehouse_location=random.choice(["WH-A1", "WH-B2", "WH-C3", "DOCK-1"]),
            vehicle_number=f"MH{random.randint(10,99)}{chr(65+i%26)}{chr(65+(i+1)%26)}{random.randint(1000,9999)}",
            quality_check_passed=True,
        )
        db.add(grn)
        db.flush()

        # GRN line items for each PO line
        po_line_items = db.query(POLineItem).filter(POLineItem.po_id == po.id).all()
        for po_line in po_line_items:
            received_qty = po_line.quantity * Decimal("0.9")  # 90% received
            grn_li = GRNLineItem(
                grn_id=grn.id,
                po_line_id=po_line.id,
                received_quantity=received_qty,
                accepted_quantity=received_qty,
                rejected_quantity=Decimal("0"),
                uom=po_line.uom,
            )
            db.add(grn_li)
            po_line.received_quantity = received_qty

        # Update PO status
        po.status = POStatus.PARTIALLY_RECEIVED
        grns.append(grn)

    db.flush()
    print(f"  ✓ {len(grns)} GRNs created")
    return grns


def seed_contracts(db: Session, vendors, cost_centers, gl_codes, users) -> list:
    if db.query(Contract).count() > 0:
        return db.query(Contract).all()

    contracts_data = [
        (1, "CON-IT-001", "IT Managed Services", "SERVICE", 12, 5000000),
        (3, "CON-IT-002", "Cloud Platform Agreement", "SERVICE", 24, 3000000),
        (5, "CON-IT-003", "IT Support & Maintenance", "SERVICE", 12, 1800000),
        (7, "CON-DEV-001", "Application Development", "SERVICE", 6, 4800000),
        (8, "CON-CONS-001", "Management Consulting Services", "CONSULTING", 3, 4500000),
        (8, "CON-ENG-001", "Civil Construction Contract", "SUPPLY", 18, 50000000),
        (15, "CON-LOG-001", "Freight & Logistics Services", "SERVICE", 12, 2160000),
        (16, "CON-COU-001", "Express Courier Services", "SERVICE", 12, 600000),
        (0, "CON-STEEL-001", "Annual Steel Supply Agreement", "SUPPLY", 12, 65000000),
        (17, "CON-AUDIT-001", "Annual Audit Services", "SERVICE", 12, 2500000),
    ]

    contracts = []
    for vi, num, title, ctype, months, value in contracts_data:
        v = vendors[vi % len(vendors)]
        start = date.today() - timedelta(days=90)
        end = start + timedelta(days=months * 30)
        c = Contract(
            contract_number=num,
            vendor_id=v.id,
            contract_type=ctype,
            title=title,
            start_date=start,
            end_date=end,
            value=Decimal(str(value)),
            status="ACTIVE",
            payment_terms=v.payment_terms,
            cost_center_id=cost_centers[0].id,
            gl_code_id=gl_codes[5].id,
            created_by=str(users[0].id),
        )
        db.add(c)
        contracts.append(c)

    db.flush()
    print(f"  ✓ {len(contracts)} contracts created")
    return contracts


def seed_lease_contracts(db: Session, vendors, cost_centers, gl_codes) -> list:
    if db.query(LeaseContract).count() > 0:
        return db.query(LeaseContract).all()

    lease_data = [
        (9, "LEASE-MUM-001", "Nariman Point Office", "Commercial", "Nariman Point, Mumbai - 400021", 850000),
        (9, "LEASE-MUM-002", "BKC Registered Office", "Commercial", "Bandra Kurla Complex, Mumbai - 400051", 1200000),
        (19, "LEASE-BLR-001", "Whitefield Tech Park", "Commercial", "Whitefield, Bangalore - 560066", 650000),
        (19, "LEASE-DLH-001", "Cyber City Gurgaon", "Commercial", "DLF Cyber City, Gurgaon - 122002", 750000),
        (9, "LEASE-PUN-001", "Hinjewadi IT Park", "Commercial", "Hinjewadi Phase 3, Pune - 411057", 450000),
        (19, "LEASE-CHN-001", "OMR Chennai Office", "Commercial", "Old Mahabalipuram Road, Chennai - 600096", 380000),
        (19, "LEASE-HYD-001", "HITEC City Office", "Commercial", "HITEC City, Hyderabad - 500081", 520000),
        (9, "LEASE-WH-001", "Bhiwandi Warehouse", "Warehouse", "Bhiwandi, Thane - 421302", 250000),
        (19, "LEASE-WH-002", "Chakan Industrial Shed", "Industrial", "Chakan MIDC, Pune - 410501", 180000),
        (19, "LEASE-VEH-001", "Fleet Vehicle Lease", "Vehicle", "Multiple Locations", 95000),
    ]

    leases = []
    for vi, num, prop_name, prop_type, addr, rent in lease_data:
        v = vendors[vi % len(vendors)]
        start = date.today() - timedelta(days=random.randint(30, 365))
        end = start + timedelta(days=1095)  # 3-year lease
        l = LeaseContract(
            contract_number=num,
            vendor_id=v.id,
            property_name=prop_name,
            property_type=prop_type,
            property_address=addr,
            monthly_rent=Decimal(str(rent)),
            security_deposit=Decimal(str(rent * 3)),
            lease_start=start,
            lease_end=end,
            lock_in_period_months=12,
            gst_applicable=True,
            gst_rate=Decimal("18"),
            tds_rate=Decimal("10"),
            escalation_percent=Decimal("5"),
            escalation_frequency_months=12,
            currency="INR",
            status="ACTIVE",
            cost_center_id=cost_centers[6].id,
            gl_code_id=gl_codes[7].id,
        )
        db.add(l)
        leases.append(l)

    db.flush()
    print(f"  ✓ {len(leases)} lease contracts created")
    return leases


def seed_assets(db: Session, vendors, cost_centers, gl_codes) -> list:
    if db.query(Asset).count() > 0:
        return db.query(Asset).all()

    n = len(vendors)
    asset_data = [
        ("AST-IT-001", "Dell PowerEdge R750 Server", "IT", vendors[1 % n].id, 850000, "Data Center"),
        ("AST-IT-002", "HP ProLiant DL380 Server", "IT", vendors[1 % n].id, 750000, "Data Center"),
        ("AST-IT-003", "Cisco Catalyst 9500 Switch", "IT", vendors[1 % n].id, 350000, "IT Room"),
        ("AST-IT-004", "NetApp Storage Array", "IT", vendors[1 % n].id, 1200000, "Data Center"),
        ("AST-IT-005", "Fortinet Firewall FG-600E", "IT", vendors[1 % n].id, 480000, "IT Room"),
        ("AST-MAC-001", "CNC Turning Machine - Mazak", "MACHINERY", vendors[3 % n].id, 8500000, "Plant-A Floor 1"),
        ("AST-MAC-002", "Industrial Lathe - Haas", "MACHINERY", vendors[3 % n].id, 12000000, "Plant-A Floor 2"),
        ("AST-MAC-003", "CNC Milling Machine - Fanuc", "MACHINERY", vendors[3 % n].id, 6500000, "Plant-B Floor 1"),
        ("AST-VEH-001", "Tata Prima 4928.S Truck", "VEHICLE", vendors[4 % n].id, 3200000, "Logistics"),
        ("AST-VEH-002", "Mahindra Scorpio - Office Use", "VEHICLE", vendors[4 % n].id, 1450000, "Admin"),
        ("AST-VEH-003", "Hyundai Creta - Sales", "VEHICLE", vendors[0 % n].id, 1200000, "Sales Team"),
        ("AST-FRN-001", "Office Workstations x50", "FURNITURE", vendors[2 % n].id, 1250000, "Head Office"),
        ("AST-FRN-002", "Conference Room Setup", "FURNITURE", vendors[2 % n].id, 850000, "Conference Room 1"),
        ("AST-ELE-001", "UPS System 20KVA - Eaton", "ELECTRICAL", vendors[2 % n].id, 625000, "Server Room"),
        ("AST-ELE-002", "Generator 500KVA - Cummins", "ELECTRICAL", vendors[4 % n].id, 2800000, "Plant"),
        ("AST-ELE-003", "Solar Panel System 100KW", "ELECTRICAL", vendors[1 % n].id, 4500000, "Rooftop"),
        ("AST-AC-001", "VRV AC System - Daikin", "ELECTRICAL", vendors[3 % n].id, 1800000, "Office Block"),
        ("AST-LAB-001", "HPLC Analyzer", "EQUIPMENT", vendors[4 % n].id, 2500000, "Quality Lab"),
        ("AST-LAB-002", "Spectrometer", "EQUIPMENT", vendors[5 % n].id, 1800000, "Quality Lab"),
        ("AST-IT-006", "Laptop Fleet x100 - Dell", "IT", vendors[0 % n].id, 6500000, "Various"),
    ]

    assets = []
    for code, name, cat, vendor_id, value, location in asset_data:
        a = Asset(
            asset_code=code,
            name=name,
            category=cat,
            vendor_id=vendor_id,
            purchase_date=date.today() - timedelta(days=random.randint(30, 730)),
            purchase_value=Decimal(str(value)),
            current_value=Decimal(str(value * 0.85)),
            location=location,
            cost_center_id=cost_centers[1].id,
            gl_code_id=gl_codes[1].id,
            status="ACTIVE",
            capitalized=True,
            capitalization_date=date.today() - timedelta(days=random.randint(15, 700)),
            depreciation_rate=Decimal("20"),
            useful_life_years=5,
        )
        db.add(a)
        assets.append(a)

    db.flush()
    print(f"  ✓ {len(assets)} assets created")
    return assets


def seed_employees(db: Session, cost_centers, users) -> list:
    if db.query(Employee).count() > 0:
        return db.query(Employee).all()

    emp_data = [
        ("EMP001", "Rohit Sharma", "rohit.sharma@company.com", "Finance", "CFO", cost_centers[2].id, 100000, 10000),
        ("EMP002", "Neha Gupta", "neha.gupta@company.com", "Finance", "Finance Manager", cost_centers[2].id, 50000, 5000),
        ("EMP003", "Arun Joshi", "arun.joshi@company.com", "IT", "IT Head", cost_centers[1].id, 75000, 8000),
        ("EMP004", "Deepa Menon", "deepa.menon@company.com", "HR", "HR Manager", cost_centers[3].id, 40000, 4000),
        ("EMP005", "Ramesh Pillai", "ramesh.pillai@company.com", "Sales", "Sales Director", cost_centers[4].id, 80000, 10000),
        ("EMP006", "Kavita Rao", "kavita.rao@company.com", "Production", "Plant Manager", cost_centers[0].id, 60000, 6000),
        ("EMP007", "Sunil Bhat", "sunil.bhat@company.com", "R&D", "R&D Head", cost_centers[5].id, 90000, 12000),
        ("EMP008", "Pooja Tiwari", "pooja.tiwari@company.com", "Admin", "Admin Manager", cost_centers[6].id, 35000, 3500),
        ("EMP009", "Manoj Kumar", "manoj.kumar@company.com", "Logistics", "Logistics Manager", cost_centers[7].id, 45000, 5000),
        ("EMP010", "Seema Verma", "seema.verma@company.com", "QA", "QA Manager", cost_centers[8].id, 40000, 4000),
        ("EMP011", "Vijay Nambiar", "vijay.nambiar@company.com", "IT", "Senior Developer", cost_centers[1].id, 35000, 3000),
        ("EMP012", "Lakshmi Devi", "lakshmi.devi@company.com", "Finance", "Senior Accountant", cost_centers[2].id, 30000, 2500),
        ("EMP013", "Arjun Singh", "arjun.singh@company.com", "Sales", "Area Manager", cost_centers[4].id, 45000, 5000),
        ("EMP014", "Meena Iyer", "meena.iyer@company.com", "HR", "Recruitment Lead", cost_centers[3].id, 28000, 2000),
        ("EMP015", "Kishore Reddy", "kishore.reddy@company.com", "Production", "Production Supervisor", cost_centers[0].id, 25000, 2000),
        ("EMP016", "Sunita Patil", "sunita.patil@company.com", "Admin", "Executive Assistant", cost_centers[6].id, 20000, 1500),
        ("EMP017", "Gaurav Mishra", "gaurav.mishra@company.com", "IT", "System Admin", cost_centers[1].id, 30000, 2500),
        ("EMP018", "Rekha Nair", "rekha.nair@company.com", "Finance", "AP Executive", cost_centers[2].id, 25000, 2000),
        ("EMP019", "Sanjay Desai", "sanjay.desai@company.com", "Sales", "Sales Executive", cost_centers[4].id, 22000, 2000),
        ("EMP020", "Asha Krishnan", "asha.krishnan@company.com", "QA", "QA Analyst", cost_centers[8].id, 20000, 1500),
    ]

    employees = []
    for code, name, email, dept, desig, cc_id, reimb, petty in emp_data:
        e = Employee(
            employee_code=code, name=name, email=email,
            department=dept, designation=desig,
            cost_center_id=cc_id,
            monthly_reimbursement_limit=Decimal(str(reimb)),
            petty_cash_limit=Decimal(str(petty)),
            daily_petty_cash_limit=Decimal(str(min(petty // 5, 2000))),
            joining_date=date.today() - timedelta(days=random.randint(180, 1800)),
            is_active=True,
        )
        db.add(e)
        employees.append(e)

    db.flush()
    print(f"  ✓ {len(employees)} employees created")
    return employees


def seed_budgets(db: Session, cost_centers, gl_codes) -> None:
    if db.query(Budget).count() > 0:
        return

    fiscal_year = "FY2024-25"
    budget_data = [
        (0, 0, 50000000),   # Manufacturing - Raw Material
        (1, 4, 10000000),   # IT - Software
        (1, 5, 15000000),   # IT - IT Services
        (2, 6, 5000000),    # Finance - Consulting
        (3, 10, 2000000),   # HR - Reimbursements
        (4, 9, 3000000),    # Sales - Travel
        (5, 0, 8000000),    # R&D - Materials
        (6, 8, 1500000),    # Admin - Utilities
        (7, 13, 12000000),  # Logistics - Transport
        (8, 0, 2000000),    # QA - Materials
    ]

    for cc_idx, gl_idx, amount in budget_data:
        b = Budget(
            cost_center_id=cost_centers[cc_idx].id,
            gl_code_id=gl_codes[gl_idx].id,
            fiscal_year=fiscal_year,
            period="ANNUAL",
            total_amount=Decimal(str(amount)),
            committed_amount=Decimal(str(amount * 0.3)),
            spent_amount=Decimal(str(amount * 0.45)),
            available_amount=Decimal(str(amount * 0.55)),
        )
        db.add(b)

    db.flush()
    print("  ✓ 10 budgets created")


def seed_approval_rules(db: Session, users) -> None:
    if db.query(ApprovalRule).count() > 0:
        return

    admin = users[0]
    finance = users[2]
    approver1 = users[3]
    approver2 = users[4]

    rules = [
        {
            "name": "Small Amount - Single Approval",
            "business_profile": None,
            "amount_min": Decimal("0"),
            "amount_max": Decimal("25000"),
            "priority": 10,
            "approval_matrix": [
                {"level": 1, "role": "AP_TEAM", "escalation_hours": 8},
            ],
        },
        {
            "name": "Medium Amount - Two Level",
            "business_profile": None,
            "amount_min": Decimal("25001"),
            "amount_max": Decimal("200000"),
            "priority": 20,
            "approval_matrix": [
                {"level": 1, "role": "AP_TEAM", "escalation_hours": 8},
                {"level": 2, "user_id": str(approver1.id), "role": "APPROVER", "escalation_hours": 16},
            ],
        },
        {
            "name": "Large Amount - Three Level",
            "business_profile": None,
            "amount_min": Decimal("200001"),
            "amount_max": Decimal("1000000"),
            "priority": 30,
            "approval_matrix": [
                {"level": 1, "role": "AP_TEAM", "escalation_hours": 8},
                {"level": 2, "user_id": str(approver1.id), "role": "APPROVER", "escalation_hours": 16},
                {"level": 3, "user_id": str(approver2.id), "role": "FINANCE", "escalation_hours": 24},
            ],
        },
        {
            "name": "High Value - CFO Approval",
            "business_profile": None,
            "amount_min": Decimal("1000001"),
            "amount_max": None,
            "priority": 40,
            "approval_matrix": [
                {"level": 1, "role": "AP_TEAM", "escalation_hours": 4},
                {"level": 2, "user_id": str(approver1.id), "role": "APPROVER", "escalation_hours": 8},
                {"level": 3, "user_id": str(approver2.id), "role": "FINANCE", "escalation_hours": 12},
                {"level": 4, "user_id": str(admin.id), "role": "ADMIN", "escalation_hours": 24},
            ],
        },
        {
            "name": "CAPEX - Special Approval",
            "business_profile": "PO_CAPEX",
            "amount_min": Decimal("0"),
            "amount_max": None,
            "priority": 50,
            "approval_matrix": [
                {"level": 1, "role": "AP_TEAM", "escalation_hours": 4},
                {"level": 2, "user_id": str(approver1.id), "role": "APPROVER", "escalation_hours": 8},
                {"level": 3, "user_id": str(finance.id), "role": "FINANCE", "escalation_hours": 12},
                {"level": 4, "user_id": str(admin.id), "role": "ADMIN", "escalation_hours": 24},
            ],
        },
    ]

    for rule_data in rules:
        rule = ApprovalRule(**rule_data)
        db.add(rule)

    db.flush()
    print(f"  ✓ {len(rules)} approval rules created")


def seed_validation_profiles(db: Session) -> None:
    if db.query(ValidationProfile).count() > 0:
        return

    profiles = [
        {
            "name": "PO Raw Material",
            "business_profile": "PO_RAW_MATERIAL",
            "rules": [
                ("PO_MANDATORY", "PO Number Present", "EXISTENCE", "FAIL", {"field": "references.po_number"}),
                ("GRN_MANDATORY", "GRN Present", "EXISTENCE", "FAIL", {"field": "references.grn_number"}),
                ("GSTIN_FORMAT", "Vendor GSTIN Format", "REGEX", "FAIL", {"field": "vendor.gstin", "pattern": "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"}),
                ("PAN_FORMAT", "Vendor PAN Format", "REGEX", "FAIL", {"field": "vendor.pan", "pattern": "^[A-Z]{5}[0-9]{4}[A-Z]{1}$"}),
                ("INVOICE_NUM", "Invoice Number", "EXISTENCE", "FAIL", {"field": "invoice.invoice_number"}),
                ("INVOICE_DATE", "Invoice Date", "EXISTENCE", "FAIL", {"field": "invoice.invoice_date"}),
                ("VENDOR_NAME", "Vendor Name", "EXISTENCE", "FAIL", {"field": "vendor.name"}),
                ("TOTAL_AMOUNT", "Total Amount > 0", "RANGE", "FAIL", {"field": "amounts.total_amount", "min": 0.01}),
            ],
        },
        {
            "name": "Non-PO Raw Material",
            "business_profile": "NON_PO_RAW_MATERIAL",
            "rules": [
                ("GSTIN_FORMAT", "Vendor GSTIN Format", "REGEX", "FAIL", {"field": "vendor.gstin", "pattern": "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"}),
                ("VENDOR_NAME", "Vendor Name", "EXISTENCE", "FAIL", {"field": "vendor.name"}),
                ("INVOICE_NUM", "Invoice Number", "EXISTENCE", "FAIL", {"field": "invoice.invoice_number"}),
                ("TOTAL_AMOUNT", "Total Amount > 0", "RANGE", "FAIL", {"field": "amounts.total_amount", "min": 0.01}),
            ],
        },
        {
            "name": "PO CAPEX",
            "business_profile": "PO_CAPEX",
            "rules": [
                ("PO_MANDATORY", "PO Number Present", "EXISTENCE", "FAIL", {"field": "references.po_number"}),
                ("ASSET_REF", "Asset Reference", "EXISTENCE", "WARNING", {"field": "references.asset_tag"}),
                ("GSTIN_FORMAT", "GSTIN Format", "REGEX", "FAIL", {"field": "vendor.gstin", "pattern": "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"}),
            ],
        },
        {
            "name": "Non-PO CAPEX",
            "business_profile": "NON_PO_CAPEX",
            "rules": [
                ("ASSET_REF", "Asset Reference Mandatory", "EXISTENCE", "FAIL", {"field": "references.asset_tag"}),
                ("VENDOR_NAME", "Vendor Name", "EXISTENCE", "FAIL", {"field": "vendor.name"}),
            ],
        },
        {
            "name": "PO OPEX",
            "business_profile": "PO_OPEX",
            "rules": [
                ("PO_MANDATORY", "PO Number Present", "EXISTENCE", "FAIL", {"field": "references.po_number"}),
                ("GSTIN_FORMAT", "GSTIN Format", "REGEX", "FAIL", {"field": "vendor.gstin", "pattern": "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"}),
            ],
        },
        {
            "name": "Non-PO OPEX",
            "business_profile": "NON_PO_OPEX",
            "rules": [
                ("VENDOR_NAME", "Vendor Name", "EXISTENCE", "FAIL", {"field": "vendor.name"}),
                ("INVOICE_NUM", "Invoice Number", "EXISTENCE", "FAIL", {"field": "invoice.invoice_number"}),
            ],
        },
        {
            "name": "Lease Rent",
            "business_profile": "LEASE_RENT",
            "rules": [
                ("LEASE_CONTRACT", "Lease Contract Reference", "EXISTENCE", "FAIL", {"field": "references.lease_contract_number"}),
                ("VENDOR_NAME", "Landlord Name", "EXISTENCE", "FAIL", {"field": "vendor.name"}),
                ("TOTAL_AMOUNT", "Rent Amount > 0", "RANGE", "FAIL", {"field": "amounts.total_amount", "min": 0.01}),
            ],
        },
        {
            "name": "Employee Reimbursement",
            "business_profile": "EMPLOYEE_REIMBURSEMENT",
            "rules": [
                ("EMPLOYEE_CODE", "Employee Code Present", "EXISTENCE", "FAIL", {"field": "references.employee_code"}),
                ("EXPENSE_CATEGORY", "Expense Category", "EXISTENCE", "WARNING", {"field": "employee_reimbursement.expense_category"}),
                ("TOTAL_AMOUNT", "Amount > 0", "RANGE", "FAIL", {"field": "amounts.total_amount", "min": 0.01}),
            ],
        },
        {
            "name": "Petty Cash",
            "business_profile": "PETTY_CASH",
            "rules": [
                ("PETTY_AMOUNT", "Petty Cash Limit <= 5000", "RANGE", "FAIL", {"field": "amounts.total_amount", "max": 5000}),
                ("EXPENSE_CAT", "Expense Category", "EXISTENCE", "WARNING", {"field": "petty_cash.expense_category"}),
            ],
        },
    ]

    for profile_data in profiles:
        rules = profile_data.pop("rules")
        vp = ValidationProfile(**profile_data)
        db.add(vp)
        db.flush()

        for sort_order, (code, name, rtype, severity, params) in enumerate(rules):
            rule = ValidationRule(
                profile_id=vp.id,
                rule_code=code,
                rule_name=name,
                rule_type=rtype,
                severity=severity,
                parameters=params,
                is_active=True,
                sort_order=sort_order,
            )
            db.add(rule)

    db.flush()
    print(f"  ✓ {len(profiles)} validation profiles created")


def seed_configurations(db: Session) -> None:
    if db.query(Configuration).count() > 0:
        return

    configs = [
        ("PRICE_TOLERANCE_PERCENT", "2.0", "MATCHING", "Price tolerance % for PO matching", "DECIMAL"),
        ("QUANTITY_TOLERANCE_PERCENT", "0.0", "MATCHING", "Quantity tolerance % for GRN matching", "DECIMAL"),
        ("TAX_TOLERANCE_PERCENT", "1.0", "MATCHING", "Tax tolerance % for matching", "DECIMAL"),
        ("OCR_CONFIDENCE_PASS", "0.85", "OCR", "OCR confidence threshold for PASS", "DECIMAL"),
        ("OCR_CONFIDENCE_WARNING", "0.70", "OCR", "OCR confidence threshold for WARNING", "DECIMAL"),
        ("BLUR_VARIANCE_GOOD", "150", "IMAGE_QUALITY", "Laplacian variance threshold for GOOD quality", "INTEGER"),
        ("SLA_AP_TEAM_HOURS", "4", "SLA", "SLA hours for AP Team queue", "INTEGER"),
        ("SLA_FINANCE_HOURS", "8", "SLA", "SLA hours for Finance queue", "INTEGER"),
        ("SLA_PROCUREMENT_HOURS", "24", "SLA", "SLA hours for Procurement queue", "INTEGER"),
        ("PETTY_CASH_LIMIT", "5000", "VALIDATION", "Maximum petty cash amount", "DECIMAL"),
        ("OPENAI_MODEL", "gpt-4o", "AI", "OpenAI model for extraction and classification", "STRING"),
        ("MAX_UPLOAD_SIZE_MB", "50", "UPLOAD", "Maximum upload file size in MB", "INTEGER"),
        ("DUPLICATE_CHECK_WINDOW_DAYS", "365", "VALIDATION", "Days window for duplicate invoice check", "INTEGER"),
    ]

    for key, value, category, desc, vtype in configs:
        c = Configuration(key=key, value=value, category=category, description=desc, value_type=vtype)
        db.add(c)

    db.flush()
    print(f"  ✓ {len(configs)} configurations created")


if __name__ == "__main__":
    seed_all()
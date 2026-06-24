"""
Seed ERP master data directly from po.xlsx and grn.xlsx (backend/sample/).

Vendors  : 9  (one per unique GSTIN/PAN from the register)
POs      : 6  (rows with a real PO number — not 'Not on Invoice' / 'Manual' get a MANUAL-* id)
GRNs     : 7  (rows that reference a real PO)

Run:
    python seed/seed_erp_from_excel.py           # skips if already loaded
    python seed/seed_erp_from_excel.py --force   # clears and reloads every time
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import date
from decimal import Decimal

# ── Path bootstrap ──────────────────────────────────────────────────────────
_candidates = ["/app", str(Path(__file__).parent.parent / "backend")]
for _c in _candidates:
    if Path(_c).exists() and Path(_c, "app", "core").exists():
        sys.path.insert(0, _c)
        break

from sqlalchemy.orm import Session
from app.core.database import SyncSessionLocal
from app.models.models import (
    Document, GRN, GRNLineItem, GRNStatus, MatchingResult,
    POLineItem, POStatus, PurchaseOrder, User, Vendor, VendorContact,
)

# ── VENDORS ─────────────────────────────────────────────────────────────────
# 9 unique vendors — one per unique GSTIN / PAN from both Excel sheets.
# Jyoti has 4 state registrations; each is a separate ERP vendor.
VENDORS = [
    {
        "vendor_code": "V-JYOTI-HR",
        "name": "Jyoti International Foods Pvt. Ltd.",
        "gstin": "06AADCJ1224D1Z8",
        "pan": "AADCJ1224D",
        "address": "NH71, Village Dhatir, Palwal 121102",
        "city": "Palwal", "state": "Haryana",
        "vendor_type": "GOODS", "vendor_category": "FOOD_SUPPLY",
        "payment_terms": "NET15",
    },
    {
        "vendor_code": "V-JYOTI-UP",
        "name": "Jyoti International Foods Pvt. Ltd.",
        "gstin": "09AADCJ1224D1Z2",
        "pan": "AADCJ1224D",
        "address": "Plot No.17, Sector 31, Kasna, Greater Noida 201310",
        "city": "Greater Noida", "state": "Uttar Pradesh",
        "vendor_type": "GOODS", "vendor_category": "FOOD_SUPPLY",
        "payment_terms": "NET15",
    },
    {
        "vendor_code": "V-JYOTI-MH",
        "name": "Jyoti International Foods Pvt. Ltd.",
        "gstin": "27AADCJ1224D1Z4",
        "pan": "AADCJ1224D",
        "address": "North Ave Rd, Kalyani Nagar, Pune 411006",
        "city": "Pune", "state": "Maharashtra",
        "vendor_type": "GOODS", "vendor_category": "FOOD_SUPPLY",
        "payment_terms": "NET15",
    },
    {
        "vendor_code": "V-JYOTI-KT",
        "name": "Jyoti International Foods Pvt. Ltd.",
        "gstin": "29AADCJ1224D1Z0",
        "pan": "AADCJ1224D",
        "address": "Sy No.36/1, Old Madras Rd, Virgonagar, Bengaluru 560049",
        "city": "Bengaluru", "state": "Karnataka",
        "vendor_type": "GOODS", "vendor_category": "FOOD_SUPPLY",
        "payment_terms": "NET15",
    },
    {
        "vendor_code": "V-ACEONE",
        "name": "Ace One Tech",
        "gstin": "06GGSPS6683F1ZI",
        "pan": "GGSPS6683F",
        "address": "OF-336, 3rd Floor, Tower A2, Spaze I Tech Park, Sector 49, Gurugram",
        "city": "Gurugram", "state": "Haryana",
        "vendor_type": "GOODS", "vendor_category": "EQUIPMENT",
        "payment_terms": "NET30",
    },
    {
        "vendor_code": "V-3MBTECH",
        "name": "3MB Technologies",
        "gstin": "27AACFZ9116G1ZY",
        "pan": "AACFZ9116G",
        "address": "140 Sarang Street, Shop No.3, Mumbai 400003",
        "city": "Mumbai", "state": "Maharashtra",
        "vendor_type": "GOODS", "vendor_category": "EQUIPMENT",
        "payment_terms": "NET30",
    },
    {
        "vendor_code": "V-DOTPE",
        "name": "Dotpe Private Limited",
        "gstin": "06AAHCD2558G1ZP",
        "pan": "AAHCD2558G",
        "address": "8th Floor, Tower D, Unitech Cyber Park, Sector 39, Gurugram",
        "city": "Gurugram", "state": "Haryana",
        "vendor_type": "SERVICES", "vendor_category": "TECHNOLOGY",
        "payment_terms": "NET45",
    },
    {
        "vendor_code": "V-ADCORP",
        "name": "A.D. Corporation",
        "gstin": "27CFSPD5059M1ZS",
        "pan": "CFSPD5059M",
        "address": "Flat No.204, A-Wing, Gajanan Heights, Thane (W) 400604",
        "city": "Thane", "state": "Maharashtra",
        "vendor_type": "SERVICES", "vendor_category": "CIVIL_WORKS",
        "payment_terms": "NET45",
    },
    {
        "vendor_code": "V-PARLEGAL",
        "name": "Paramount Legal",
        "gstin": None,                 # No GST — legal firm
        "pan": "ABDFP9314N",
        "address": "273/5, Durgapuri Extension, Shahdara, New Delhi 110093",
        "city": "New Delhi", "state": "Delhi",
        "vendor_type": "SERVICES", "vendor_category": "LEGAL",
        "payment_terms": "NET30",
    },
]

# ── PURCHASE ORDERS ──────────────────────────────────────────────────────────
# Exact amounts from po.xlsx.
# IO-56969-2-0-000 is a blanket PO covering multiple Jyoti state entities;
# primary vendor is V-JYOTI-HR.  V-JYOTI-MH invoices will show PARTIAL_MATCH
# on vendor field (cross-entity billing) — which is a realistic scenario.
POS = [
    {
        "po_number": "IO-56969-2-0-000",
        "vendor_code": "V-JYOTI-HR",
        "po_date": date(2026, 2, 27),
        "total_amount": Decimal("3000.00"),   # blanket — covers HR 1105.85 + MH 1076.34 + future
        "description": "Blanket supply PO — food items, consumables, uniforms (Store 56969 / JC04745)",
        "payment_terms": "NET15",
        "status": POStatus.OPEN,
        "line_items": [
            {
                "line_number": 1,
                "description": "Food & consumables — blanket supply (various SKUs, Store 56969)",
                "quantity": Decimal("10"),
                "unit_price": Decimal("300.00"),
                "uom": "Case",
                "total_amount": Decimal("3000.00"),
                "igst_rate": Decimal("5.62"),
                "cgst_rate": Decimal("0"),
                "sgst_rate": Decimal("0"),
            },
        ],
    },
    {
        "po_number": "CP-2526-007601",
        "vendor_code": "V-ACEONE",
        "po_date": date(2026, 2, 10),
        "total_amount": Decimal("36462.00"),
        "description": "Air Curtain 4Ft, Weighing Scale, Crates, Fire Extinguishers (6kg ABC + CO2 4.5kg)",
        "payment_terms": "NET30",
        "status": POStatus.OPEN,
        "line_items": [
            {
                "line_number": 1,
                "description": "Air Curtain 4Ft",
                "quantity": Decimal("1"),
                "unit_price": Decimal("8475.00"),
                "uom": "Nos",
                "total_amount": Decimal("8475.00"),
                "igst_rate": Decimal("18"),
                "cgst_rate": Decimal("0"),
                "sgst_rate": Decimal("0"),
            },
            {
                "line_number": 2,
                "description": "Weighing Scale",
                "quantity": Decimal("1"),
                "unit_price": Decimal("4237.00"),
                "uom": "Nos",
                "total_amount": Decimal("4237.00"),
                "igst_rate": Decimal("18"),
                "cgst_rate": Decimal("0"),
                "sgst_rate": Decimal("0"),
            },
            {
                "line_number": 3,
                "description": "Crates",
                "quantity": Decimal("12"),
                "unit_price": Decimal("847.00"),
                "uom": "Nos",
                "total_amount": Decimal("10164.00"),
                "igst_rate": Decimal("18"),
                "cgst_rate": Decimal("0"),
                "sgst_rate": Decimal("0"),
            },
            {
                "line_number": 4,
                "description": "Fire Extinguisher 6kg ABC + CO2 Fire Extinguisher 4.5kg",
                "quantity": Decimal("2"),
                "unit_price": Decimal("3762.00"),
                "uom": "Nos",
                "total_amount": Decimal("7524.00"),
                "igst_rate": Decimal("18"),
                "cgst_rate": Decimal("0"),
                "sgst_rate": Decimal("0"),
            },
        ],
    },
    {
        "po_number": "CP-2526-007940",
        "vendor_code": "V-3MBTECH",
        "po_date": date(2026, 2, 18),
        "total_amount": Decimal("21181.00"),
        "description": "Cup Sealing Machine Red Frame — S.N. 2526022297 + Freight",
        "payment_terms": "NET30",
        "status": POStatus.OPEN,
        "line_items": [
            {
                "line_number": 1,
                "description": "Cup Sealing Machine Red Frame (S.N.2526022297)",
                "quantity": Decimal("1"),
                "unit_price": Decimal("17950.00"),
                "uom": "Nos",
                "total_amount": Decimal("17950.00"),
                "cgst_rate": Decimal("9"),
                "sgst_rate": Decimal("9"),
                "igst_rate": Decimal("0"),
            },
        ],
    },
    {
        "po_number": "CP-2526-007884",
        "vendor_code": "V-DOTPE",
        "po_date": date(2026, 2, 23),
        "total_amount": Decimal("119388.54"),
        "description": "POS Terminal PS6216 i5 + Cash Drawer CR410B + RP326 Printer + "
                       "LM6810U Display + Keyboard & Mouse + Installation",
        "payment_terms": "NET45",
        "status": POStatus.OPEN,
        # Per-line breakdown mirrors the vendor's actual invoice (DOT/26/02/55)
        # line items 1:1 — so 3-way item matching pairs correctly instead of
        # only reconciling at the PO-total level.
        "line_items": [
            {
                "line_number": 1,
                "description": "PS6216 i5 11th gen 15.6\" touch terminal +Win 11 +Wi-Fi",
                "item_code": "PSQ21500",
                "hsn_sac_code": "84714900",
                "quantity": Decimal("1"),
                "unit_price": Decimal("75000.00"),
                "uom": "Pcs",
                "total_amount": Decimal("75000.00"),
                "igst_rate": Decimal("18"),
                "cgst_rate": Decimal("0"),
                "sgst_rate": Decimal("0"),
            },
            {
                "line_number": 2,
                "description": "Cash Drawer CR410B",
                "item_code": "251118103882",
                "hsn_sac_code": "84732900",
                "quantity": Decimal("1"),
                "unit_price": Decimal("3160.00"),
                "uom": "Pcs",
                "total_amount": Decimal("3160.00"),
                "igst_rate": Decimal("18"),
                "cgst_rate": Decimal("0"),
                "sgst_rate": Decimal("0"),
            },
            {
                "line_number": 3,
                "description": "RP326 Printer",
                "item_code": "3262509090953",
                "hsn_sac_code": "84433290",
                "quantity": Decimal("1"),
                "unit_price": Decimal("7400.00"),
                "uom": "Pcs",
                "total_amount": Decimal("7400.00"),
                "igst_rate": Decimal("18"),
                "cgst_rate": Decimal("0"),
                "sgst_rate": Decimal("0"),
            },
            {
                "line_number": 4,
                "description": "LM6810 U Non touch Display",
                "item_code": "LMPAO227",
                "hsn_sac_code": "85285900",
                "quantity": Decimal("1"),
                "unit_price": Decimal("13693.00"),
                "uom": "Pcs",
                "total_amount": Decimal("13693.00"),
                "igst_rate": Decimal("18"),
                "cgst_rate": Decimal("0"),
                "sgst_rate": Decimal("0"),
            },
            {
                "line_number": 5,
                "description": "Wired Keyboard & Mouse Combo",
                "item_code": "IN55440490",
                "hsn_sac_code": "84716040",
                "quantity": Decimal("1"),
                "unit_price": Decimal("423.73"),
                "uom": "Pcs",
                "total_amount": Decimal("423.73"),
                "igst_rate": Decimal("18"),
                "cgst_rate": Decimal("0"),
                "sgst_rate": Decimal("0"),
            },
            {
                "line_number": 6,
                "description": "Installation & Commissioning Charges",
                "hsn_sac_code": "998713",
                "quantity": Decimal("1"),
                "unit_price": Decimal("1500.00"),
                "uom": "Nos",
                "total_amount": Decimal("1500.00"),
                "igst_rate": Decimal("18"),
                "cgst_rate": Decimal("0"),
                "sgst_rate": Decimal("0"),
            },
        ],
    },
    {
        "po_number": "CP-2526-002494",
        "vendor_code": "V-ADCORP",
        "po_date": date(2025, 8, 13),
        "total_amount": Decimal("1002418.57"),
        "description": "General Civil, Electrical & Plumbing Work — Bytco Point Nashik (Lump Sum)",
        "payment_terms": "NET45",
        "status": POStatus.OPEN,
        "line_items": [
            {
                "line_number": 1,
                "description": "General Civil, Electrical & Plumbing Work — Bytco Point Nashik (Lump Sum)",
                "quantity": Decimal("1"),
                "unit_price": Decimal("849507.27"),
                "uom": "LS",
                "total_amount": Decimal("849507.27"),
                "cgst_rate": Decimal("9"),
                "sgst_rate": Decimal("9"),
                "igst_rate": Decimal("0"),
            },
        ],
    },
]

# ── GRNS ─────────────────────────────────────────────────────────────────────
# Only rows with a real PO number. GRNs 2,3,10 (Not on Invoice) are skipped
# because grns.po_id is NOT NULL.
GRNS = [
    {
        "grn_number": "GRN-2526-001",
        "po_number": "IO-56969-2-0-000",
        "vendor_code": "V-JYOTI-HR",
        "received_date": date(2026, 2, 27),
        "status": GRNStatus.ACCEPTED,
        "description": "Red Chilli Sauce Cremica 1X12X1000gram (1 Case) + Freight",
        "warehouse_location": "Store 56969 — Dehradun, UK",
        "quality_check_passed": True,
        "accepted_qty": Decimal("1"),
        "uom": "Case",
    },
    {
        "grn_number": "GRN-2526-004",
        "po_number": "IO-56969-2-0-000",
        "vendor_code": "V-JYOTI-MH",   # Pune entity billed against blanket PO
        "received_date": date(2026, 1, 12),
        "status": GRNStatus.ACCEPTED,
        "description": "5-Panel Caps Std Size Iris (3 Pcs) + Waist Apron Choice Mark Iris (2 Pcs) + Freight",
        "warehouse_location": "Store 56969 — Pune, MH",
        "quality_check_passed": True,
        "accepted_qty": Decimal("6"),
        "uom": "Mixed",
    },
    {
        "grn_number": "GRN-2526-006",
        "po_number": "CP-2526-007601",
        "vendor_code": "V-ACEONE",
        "received_date": date(2026, 3, 17),
        "status": GRNStatus.ACCEPTED,
        "description": "Air Curtain 4Ft (1) + Weighing Scale (1) + Crates (12) + "
                       "Fire Extinguisher 6kg ABC (1) + CO2 4.5kg (1)",
        "warehouse_location": "Karnataka — Bengaluru site",
        "quality_check_passed": True,
        "accepted_qty": Decimal("16"),
        "uom": "Nos",
    },
    {
        "grn_number": "GRN-2526-007",
        "po_number": "CP-2526-007940",
        "vendor_code": "V-3MBTECH",
        "received_date": date(2026, 2, 24),
        "status": GRNStatus.ACCEPTED,
        "description": "Cup Sealing Machine Red Frame — S.N.2526022297 (1 Nos) + Freight",
        "warehouse_location": "Maharashtra store",
        "quality_check_passed": True,
        "accepted_qty": Decimal("1"),
        "uom": "Nos",
    },
    {
        "grn_number": "GRN-2526-008",
        "po_number": "CP-2526-007884",
        "vendor_code": "V-DOTPE",
        "received_date": date(2026, 2, 23),
        "status": GRNStatus.ACCEPTED,
        "description": "POS Terminal PS6216 i5 (1) + Cash Drawer CR410B (1) + RP326 Printer (1) + "
                       "LM6810U Display (1) + Keyboard & Mouse (1) + Installation",
        "warehouse_location": "Delhi site",
        "quality_check_passed": True,
        "accepted_qty": Decimal("5"),
        "uom": "Pcs",
    },
    {
        "grn_number": "GRN-2526-009",
        "po_number": "CP-2526-002494",
        "vendor_code": "V-ADCORP",
        "received_date": date(2026, 1, 31),
        "status": GRNStatus.ACCEPTED,
        "description": "General Civil, Electrical & Plumbing Work — Bytco Point Nashik (Lump Sum)",
        "warehouse_location": "Nashik site — Bytco Point",
        "quality_check_passed": True,
        "accepted_qty": Decimal("1"),
        "uom": "LS",
    },
]


# ── helpers ──────────────────────────────────────────────────────────────────

def _all_excel_codes():
    return [v["vendor_code"] for v in VENDORS]


def _already_loaded(db: Session) -> bool:
    """True when all 9 Excel vendors are present in the DB."""
    loaded = db.query(Vendor).filter(
        Vendor.vendor_code.in_(_all_excel_codes())
    ).count()
    return loaded >= len(VENDORS)


def clear_erp_data(db: Session) -> None:
    print("  Nullifying document FK references...")
    db.query(Document).update(
        {"vendor_id": None, "po_id": None, "grn_id": None},
        synchronize_session=False,
    )
    db.flush()

    print("  Clearing matching results...")
    db.query(MatchingResult).delete(synchronize_session=False)
    db.flush()

    print("  Clearing GRNs...")
    db.query(GRNLineItem).delete(synchronize_session=False)
    db.query(GRN).delete(synchronize_session=False)
    db.flush()

    print("  Clearing purchase orders...")
    db.query(POLineItem).delete(synchronize_session=False)
    db.query(PurchaseOrder).delete(synchronize_session=False)
    db.flush()

    print("  Clearing vendors...")
    db.query(VendorContact).delete(synchronize_session=False)
    db.query(Vendor).delete(synchronize_session=False)
    db.flush()
    print("  Cleared.")


def seed_vendors(db: Session) -> dict[str, Vendor]:
    vendor_map: dict[str, Vendor] = {}
    for vd in VENDORS:
        v = Vendor(
            vendor_code=vd["vendor_code"],
            name=vd["name"],
            gstin=vd.get("gstin"),
            pan=vd.get("pan"),
            address_line1=vd.get("address"),
            city=vd.get("city"),
            state=vd.get("state"),
            country="India",
            vendor_type=vd.get("vendor_type", "GOODS"),
            vendor_category=vd.get("vendor_category"),
            payment_terms=vd.get("payment_terms", "NET30"),
            currency="INR",
            credit_limit=Decimal("2000000"),
            is_approved=True,
            tds_applicable=vd.get("vendor_type") == "SERVICES",
            tds_rate=Decimal("10") if vd.get("vendor_type") == "SERVICES" else Decimal("0"),
        )
        db.add(v)
        db.flush()
        vendor_map[vd["vendor_code"]] = v

        db.add(VendorContact(
            vendor_id=v.id,
            name=f"Accounts — {vd['name'].split()[0]}",
            email=f"billing@{vd['vendor_code'].lower().replace('-', '')}.com",
            designation="Accounts Manager",
            is_primary=True,
            contact_type="BILLING",
        ))

    db.flush()
    print(f"  Created {len(vendor_map)} vendors")
    return vendor_map


def seed_purchase_orders(db: Session, vendor_map: dict, admin_user) -> dict[str, PurchaseOrder]:
    po_map: dict[str, PurchaseOrder] = {}
    for pd in POS:
        vendor = vendor_map[pd["vendor_code"]]
        po = PurchaseOrder(
            po_number=pd["po_number"],
            vendor_id=vendor.id,
            status=pd.get("status", POStatus.OPEN),
            total_amount=pd["total_amount"],
            invoiced_amount=Decimal("0"),
            currency="INR",
            payment_terms=pd.get("payment_terms", "NET30"),
            po_date=pd["po_date"],
            description=pd.get("description"),
            created_by=str(admin_user.id),
        )
        db.add(po)
        db.flush()

        for li in pd.get("line_items", []):
            db.add(POLineItem(
                po_id=po.id,
                line_number=li["line_number"],
                item_code=li.get("item_code"),
                hsn_sac_code=li.get("hsn_sac_code"),
                description=li["description"],
                quantity=li["quantity"],
                unit_price=li["unit_price"],
                uom=li["uom"],
                total_amount=li["total_amount"],
                cgst_rate=li.get("cgst_rate", Decimal("0")),
                sgst_rate=li.get("sgst_rate", Decimal("0")),
                igst_rate=li.get("igst_rate", Decimal("0")),
            ))

        po_map[pd["po_number"]] = po

    db.flush()
    print(f"  Created {len(po_map)} purchase orders")
    return po_map


def seed_grns(db: Session, vendor_map: dict, po_map: dict, admin_user) -> list:
    created = []
    for gd in GRNS:
        po = po_map.get(gd["po_number"])
        vendor = vendor_map.get(gd["vendor_code"])
        if not po or not vendor:
            print(f"  SKIP {gd['grn_number']} — PO/vendor not found")
            continue

        po_lines = db.query(POLineItem).filter(POLineItem.po_id == po.id).all()
        if not po_lines:
            print(f"  SKIP {gd['grn_number']} — no PO line items")
            continue

        grn = GRN(
            grn_number=gd["grn_number"],
            po_id=po.id,
            vendor_id=vendor.id,
            received_date=gd["received_date"],
            status=gd.get("status", GRNStatus.ACCEPTED),
            received_by=str(admin_user.id),
            warehouse_location=gd.get("warehouse_location"),
            quality_check_passed=gd.get("quality_check_passed", True),
            remarks=gd.get("description"),
        )
        db.add(grn)
        db.flush()

        # One GRN line per PO line — each fully received/accepted (the
        # register's "Accepted" condition applies to the whole shipment).
        # A single combined row (old behaviour) misrepresented every PO
        # line's received qty as the GRN's total piece-count, which made
        # 3-way line matching fail on multi-line POs (e.g. comparing a PO
        # line qty of 1 against a GRN row meant to summarise 5-6 lines).
        for po_line in po_lines:
            db.add(GRNLineItem(
                grn_id=grn.id,
                po_line_id=po_line.id,
                received_quantity=po_line.quantity,
                accepted_quantity=po_line.quantity,
                rejected_quantity=Decimal("0"),
                uom=po_line.uom,
            ))
        created.append(grn)

    db.flush()
    print(f"  Created {len(created)} GRNs")
    return created


# ── entry point ──────────────────────────────────────────────────────────────

def run():
    force = "--force" in sys.argv

    db = SyncSessionLocal()
    try:
        if _already_loaded(db) and not force:
            v = db.query(Vendor).count()
            p = db.query(PurchaseOrder).count()
            g = db.query(GRN).count()
            print(f"✅  Excel ERP data already present — {v} vendors, {p} POs, {g} GRNs. Skipping.")
            print("    Run with --force to replace.")
            return

        print("🗑️  Clearing old ERP data...")
        clear_erp_data(db)

        admin_user = (
            db.query(User).filter(User.email == "admin@company.com").first()
            or db.query(User).first()
        )
        if not admin_user:
            raise RuntimeError("No users found — run seed.py first.")

        print("📦  Seeding vendors...")
        vendor_map = seed_vendors(db)

        print("📄  Seeding purchase orders...")
        po_map = seed_purchase_orders(db, vendor_map, admin_user)

        print("📦  Seeding GRNs...")
        seed_grns(db, vendor_map, po_map, admin_user)

        db.commit()

        print()
        print("✅  ERP data loaded from Excel register!")
        print(f"   Vendors : {len(vendor_map)}")
        print(f"   POs     : {len(po_map)}")
        print()
        print("   Vendor → PO mapping:")
        for pd in POS:
            v = vendor_map[pd["vendor_code"]]
            print(f"     {pd['po_number']:30s}  →  {v.vendor_code}  ({v.name[:40]})  GSTIN: {v.gstin or v.pan}")

    except Exception as e:
        db.rollback()
        print(f"❌  Failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()

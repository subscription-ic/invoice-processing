"""
Clear the entire ERP/transactional data and create Mock ERP data that matches
the attached Jyoti International Foods invoices.

Real POs present on the invoices (these get PO + GRN for true 3-way matching):
  - Invoice 250143208 → PO IO-56969-2-0-000037 (Red Chilli Sauce + Freight)
  - Invoice 250270929 → PO IO-56969-2-0-000014 (Caps + Apron + Freight)
Invoices with NO PO (250203907, 250207777, 250416911-"Manual") stay NON-PO.

Vendors are created per GST registration (same PAN, different state GSTIN),
all with po_required = FALSE (so no-PO invoices are NOT force-linked to a PO).

Run from backend/:  python ..\seed\reset_jyoti.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import date
from decimal import Decimal

_candidates = ["/app", str(Path(__file__).parent.parent / "backend")]
for _c in _candidates:
    if Path(_c, "app", "core").exists():
        sys.path.insert(0, _c)
        break

from sqlalchemy import text
from app.core.database import SyncSessionLocal
from app.models.models import (
    User, Vendor, PurchaseOrder, POLineItem, GRN, GRNLineItem,
    CostCenter, GLCode, POStatus, GRNStatus,
)

TRANSACTIONAL = [
    "audit_logs", "notifications", "payment_schedules", "erp_postings",
    "approvals", "exceptions", "matching_results", "validation_results",
    "document_line_items", "workflow_states", "documents",
]
MASTER = [
    "grn_line_items", "grns", "po_line_items", "purchase_orders",
    "lease_contracts", "contracts", "assets", "vendor_contacts", "vendors",
]

# GST registrations of Jyoti International Foods (same PAN AADCJ1224D)
VENDORS = [
    ("V-JYOTI-HR", "06AADCJ1224D1Z8", "Palwal", "Haryana"),
    ("V-JYOTI-UP", "09AADCJ1224D1Z2", "Greater Noida", "Uttar Pradesh"),
    ("V-JYOTI-MH", "27AADCJ1224D1Z4", "Pune", "Maharashtra"),
    ("V-JYOTI-KA", "29AADCJ1224D1Z0", "Bengaluru", "Karnataka"),
]


def main():
    db = SyncSessionLocal()
    try:
        for t in TRANSACTIONAL + MASTER:
            db.execute(text(f"DELETE FROM {t}"))
        db.commit()
        print("Cleared all transactional + master data.")

        admin = db.query(User).first()
        cc = db.query(CostCenter).first()
        gl = db.query(GLCode).first()
        admin_id = str(admin.id) if admin else None

        vmap = {}
        for code, gstin, city, state in VENDORS:
            v = Vendor(
                vendor_code=code, name="Jyoti International Foods Pvt. Ltd.",
                gstin=gstin, pan="AADCJ1224D", city=city, state=state, country="India",
                bank_name="HDFC Bank", bank_account_number="50200005020226",
                bank_ifsc="HDFC0000539", payment_terms="NET15",
                vendor_type="GOODS", vendor_category="FOOD",
                is_approved=True, credit_limit=Decimal("10000000"),
                po_required=False,  # do NOT force no-PO invoices onto a PO
            )
            db.add(v); db.flush()
            vmap[gstin] = v
        print(f"Created {len(vmap)} vendor registrations.")

        def make_po(po_number, vendor, po_date, lines):
            total = sum(Decimal(str(q)) * Decimal(str(p)) for _, _, _, q, p, _, _ in lines)
            po = PurchaseOrder(
                po_number=po_number, vendor_id=vendor.id, status=POStatus.OPEN,
                total_amount=total, currency="INR",
                cost_center_id=cc.id if cc else None, gl_code_id=gl.id if gl else None,
                payment_terms="NET15", po_date=po_date, description="Goods supply PO",
                created_by=admin_id,
            )
            db.add(po); db.flush()
            po_lines = []
            for i, (code, desc, hsn, qty, price, uom, igst) in enumerate(lines, start=1):
                pl = POLineItem(
                    po_id=po.id, line_number=i, item_code=code, description=desc,
                    hsn_sac_code=hsn, quantity=Decimal(str(qty)), unit_price=Decimal(str(price)),
                    uom=uom, total_amount=Decimal(str(qty)) * Decimal(str(price)),
                    igst_rate=Decimal(str(igst)),
                )
                db.add(pl); po_lines.append(pl)
            db.flush()
            # GRN: goods received = full PO qty
            grn = GRN(grn_number=f"GRN-{po_number[-6:]}", po_id=po.id, vendor_id=vendor.id,
                      received_date=po_date, status=GRNStatus.ACCEPTED, received_by=admin_id,
                      warehouse_location="Store Warehouse", quality_check_passed=True)
            db.add(grn); db.flush()
            for pl in po_lines:
                db.add(GRNLineItem(grn_id=grn.id, po_line_id=pl.id,
                                   received_quantity=pl.quantity, accepted_quantity=pl.quantity, uom=pl.uom))
            db.flush()
            return po

        # PO for invoice 250143208 (Red Chilli Sauce + Freight) — vendor 06 (HR)
        make_po("IO-56969-2-0-000037", vmap["06AADCJ1224D1Z8"], date(2026, 2, 20), [
            ("D11011C", "Red Chilli Sauce Cremica", "21039020", 1, 997.00, "Case", 5),
            ("NI015", "Freight", "996812", 1, 50.00, "EA", 18),
        ])
        # PO for invoice 250270929 (Caps + Apron + Freight) — vendor 27 (MH)
        make_po("IO-56969-2-0-000014", vmap["27AADCJ1224D1Z4"], date(2026, 1, 5), [
            ("JI11007A", "5 Panel Caps Standard Size - Iris", "65050090", 3, 151.96, "Pcs", 5),
            ("JI11008A", "Waist Apron with Choice mark - Iris", "62171010", 2, 144.13, "Pcs", 5),
            ("NI013", "Freight Charges-UF", "996812", 1, 250.00, "EA", 18),
        ])
        db.commit()
        print("\n✅ Done. Mock ERP for Jyoti invoices created:")
        print("   PO IO-56969-2-0-000037 + GRN  → invoice 250143208 (3-way match)")
        print("   PO IO-56969-2-0-000014 + GRN  → invoice 250270929 (3-way match)")
        print("   No-PO invoices (250203907, 250207777, 250416911) → NON-PO path")
    except Exception as e:
        db.rollback()
        print(f"❌ Failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
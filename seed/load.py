"""
Generic JSON-fixture loader for the Mock ERP.

Reads seed/data/*.json (vendors, purchase_orders, grns), resolves foreign keys
by natural keys (vendor_code, po_number, item_code), and inserts in FK-safe order.

Run from backend/:  python ..\seed\load.py
Add/edit ERP data by editing the JSON files — no code change needed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal

_HERE = Path(__file__).parent
_candidates = ["/app", str(_HERE.parent / "backend")]
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

DATA = _HERE / "data"

# Cleared before load (children → parents)
TRANSACTIONAL = [
    "audit_logs", "notifications", "payment_schedules", "erp_postings",
    "approvals", "exceptions", "matching_results", "validation_results",
    "document_line_items", "workflow_states", "documents",
]
MASTER = [
    "grn_line_items", "grns", "po_line_items", "purchase_orders",
    "lease_contracts", "contracts", "assets", "vendor_contacts", "vendors",
]


def _load_json(name: str):
    path = DATA / name
    if not path.exists():
        print(f"   (skip {name} — not found)")
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _dt(s):
    return datetime.strptime(s, "%Y-%m-%d").date() if s else None


def main():
    db = SyncSessionLocal()
    try:
        # 1. Clear existing data
        for t in TRANSACTIONAL + MASTER:
            db.execute(text(f"DELETE FROM {t}"))
        db.commit()
        print("Cleared transactional + master data.")

        admin = db.query(User).first()
        admin_id = str(admin.id) if admin else None
        cc = db.query(CostCenter).first()
        gl = db.query(GLCode).first()
        cc_id = cc.id if cc else None
        gl_id = gl.id if gl else None

        # 2. Vendors  (natural key: vendor_code)
        vendors = {}
        for v in _load_json("vendors.json"):
            row = Vendor(
                vendor_code=v["vendor_code"], name=v["name"], gstin=v.get("gstin"),
                pan=v.get("pan"), city=v.get("city"), state=v.get("state"), country="India",
                bank_name=v.get("bank_name"), bank_account_number=v.get("bank_account_number"),
                bank_ifsc=v.get("bank_ifsc"), payment_terms=v.get("payment_terms", "NET30"),
                vendor_type=v.get("vendor_type", "GOODS"), vendor_category=v.get("vendor_category"),
                is_approved=v.get("is_approved", True), po_required=v.get("po_required", False),
                credit_limit=Decimal(str(v.get("credit_limit", 0))),
            )
            db.add(row); db.flush()
            vendors[v["vendor_code"]] = row
        print(f"Loaded {len(vendors)} vendors.")

        # 3. Purchase Orders + lines  (FK: vendor_code → vendor.id)
        pos = {}                       # po_number -> PurchaseOrder
        po_line_index = {}             # (po_number, item_code) -> POLineItem
        for p in _load_json("purchase_orders.json"):
            vendor = vendors.get(p["vendor_code"])
            if not vendor:
                print(f"   ! PO {p['po_number']}: vendor_code {p['vendor_code']} not found — skipped")
                continue
            total = sum(Decimal(str(l["qty"])) * Decimal(str(l["price"])) for l in p["lines"])
            po = PurchaseOrder(
                po_number=p["po_number"], vendor_id=vendor.id, status=POStatus.OPEN,
                total_amount=total, currency="INR", cost_center_id=cc_id, gl_code_id=gl_id,
                payment_terms=p.get("payment_terms", "NET30"), po_date=_dt(p.get("po_date")),
                description=p.get("description"), created_by=admin_id,
            )
            db.add(po); db.flush()
            pos[p["po_number"]] = po
            for i, l in enumerate(p["lines"], start=1):
                pl = POLineItem(
                    po_id=po.id, line_number=i, item_code=l.get("item_code"),
                    description=l["description"], hsn_sac_code=l.get("hsn"),
                    quantity=Decimal(str(l["qty"])), unit_price=Decimal(str(l["price"])),
                    uom=l.get("uom", "EA"), total_amount=Decimal(str(l["qty"])) * Decimal(str(l["price"])),
                    igst_rate=Decimal(str(l.get("igst", 0))),
                )
                db.add(pl); db.flush()
                po_line_index[(p["po_number"], l.get("item_code"))] = pl
        print(f"Loaded {len(pos)} purchase orders.")

        # 4. GRNs + lines  (FK: po_number → po.id, item_code → po_line.id)
        grn_count = 0
        for g in _load_json("grns.json"):
            po = pos.get(g["po_number"])
            if not po:
                print(f"   ! GRN {g['grn_number']}: po_number {g['po_number']} not found — skipped")
                continue
            grn = GRN(
                grn_number=g["grn_number"], po_id=po.id, vendor_id=po.vendor_id,
                received_date=_dt(g.get("received_date")), status=GRNStatus.ACCEPTED,
                received_by=admin_id, warehouse_location=g.get("warehouse_location"),
                quality_check_passed=True,
            )
            db.add(grn); db.flush()
            for l in g["lines"]:
                pl = po_line_index.get((g["po_number"], l.get("item_code")))
                if not pl:
                    continue
                db.add(GRNLineItem(
                    grn_id=grn.id, po_line_id=pl.id,
                    received_quantity=Decimal(str(l["received_qty"])),
                    accepted_quantity=Decimal(str(l.get("accepted_qty", l["received_qty"]))),
                    uom=l.get("uom", "EA"),
                ))
            db.flush()
            grn_count += 1
        print(f"Loaded {grn_count} GRNs.")

        db.commit()
        print("\n✅ JSON fixtures loaded. Edit seed/data/*.json to change the Mock ERP.")
    except Exception as e:
        db.rollback()
        print(f"❌ Failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
"""
Clear all document/processing data but KEEP master data (vendors, POs, GRNs,
employees, contracts, approval rules, validation profiles) and users.
Usage:  python seed/clear_documents.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_candidates = ["/app", str(Path(__file__).parent.parent / "backend")]
_backend_dir = None
for _c in _candidates:
    if Path(_c, "app", "core").exists():
        sys.path.insert(0, _c)
        _backend_dir = _c
        break

from sqlalchemy import text
from app.core.database import SyncSessionLocal
from app.core.config import settings


# Order matters — children before parents (FK constraints)
TABLES = [
    "audit_logs",
    "notifications",
    "payment_schedules",
    "erp_postings",
    "approvals",
    "exceptions",
    "matching_results",
    "validation_results",
    "document_line_items",
    "workflow_states",
    "documents",
]


def main():
    db = SyncSessionLocal()
    try:
        for table in TABLES:
            db.execute(text(f"DELETE FROM {table}"))
            print(f"  cleared {table}")

        # Reset PO/blanket-PO draw-down — invoiced_quantity/invoiced_amount and
        # status are a *consequence* of the documents we just deleted, not
        # master data. Without this, a re-test after clearing documents sees
        # "no remaining balance" on POs already drawn down by the deleted
        # invoices, so open-PO resolution silently stops finding them.
        db.execute(text("UPDATE po_line_items SET invoiced_quantity = 0"))
        db.execute(text("UPDATE purchase_orders SET invoiced_amount = 0, status = 'OPEN'"))
        print("  reset PO/PO-line draw-down (invoiced_quantity, invoiced_amount, status)")

        db.commit()
        print("\nDone. All documents and processing records removed.")
        print("Master data (vendors, POs, users, rules) preserved.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()

    _clear_uploaded_files()


def _clear_uploaded_files() -> None:
    """Remove orphaned uploaded files (raw/extracted/ocr/processed/final/exceptions)
    left on disk from documents we just deleted from the DB."""
    upload_dir = Path(settings.UPLOAD_DIR)
    if not upload_dir.exists() and _backend_dir:
        # UPLOAD_DIR is relative (e.g. "./uploads") and resolves against CWD,
        # which differs when this script is run from the repo root vs backend/.
        upload_dir = Path(_backend_dir) / "uploads"
    if not upload_dir.exists():
        return
    removed = 0
    for sub in ("raw", "extracted", "ocr", "processed", "final", "exceptions"):
        folder = upload_dir / sub
        if not folder.exists():
            continue
        for f in folder.iterdir():
            if f.is_file():
                f.unlink()
                removed += 1
    print(f"  removed {removed} orphaned files from {upload_dir}")


if __name__ == "__main__":
    main()
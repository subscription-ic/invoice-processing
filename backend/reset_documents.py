"""
Run from the backend/ directory:
    python reset_documents.py

Deletes every document-related row from the database AND clears the uploads folder.
Master data (vendors, POs, GRNs, users, etc.) is left untouched.
"""
import os
import shutil
import sys
from pathlib import Path

# Make sure the app package is importable
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from app.core.database import SyncSessionLocal
from app.core.config import settings
from sqlalchemy import text

TABLES_TO_CLEAR = [
    # child tables first (FK order)
    "audit_logs",
    "notifications",
    "document_line_items",
    "validation_results",
    "matching_results",
    "exceptions",
    "approvals",
    "erp_postings",
    "payment_schedules",
    "workflow_states",
    "workflow_state_archive",
    "documents",
]

def clear_db():
    db = SyncSessionLocal()
    try:
        print("Clearing document-related tables...")
        for table in TABLES_TO_CLEAR:
            result = db.execute(text(f"DELETE FROM {table}"))
            print(f"  {table}: {result.rowcount} rows deleted")
        db.commit()
        print("Database cleared.\n")
    except Exception as e:
        db.rollback()
        print(f"DB error: {e}")
        raise
    finally:
        db.close()

def clear_uploads():
    upload_dir = Path(settings.UPLOAD_DIR)
    if not upload_dir.exists():
        print(f"Upload dir '{upload_dir}' does not exist, skipping.")
        return

    count = 0
    for item in upload_dir.iterdir():
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            count += 1
        except Exception as e:
            print(f"  Could not remove {item}: {e}")

    print(f"Uploads folder cleared: {count} items removed from '{upload_dir}'.\n")

if __name__ == "__main__":
    print("=== Document Reset ===\n")
    clear_db()
    clear_uploads()
    print("Done. Start fresh!")

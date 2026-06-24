"""
Diagnose why a document is stuck 'Queued'.
Usage:  python seed/check_pipeline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_candidates = ["/app", str(Path(__file__).parent.parent / "backend")]
for _c in _candidates:
    if Path(_c, "app", "core").exists():
        sys.path.insert(0, _c)
        break

from app.core.config import settings
from app.core.database import SyncSessionLocal
from app.models.models import Document, WorkflowState, AuditLog


def main():
    print("=" * 60)
    print("1) REDIS / CELERY BROKER CHECK")
    print("=" * 60)
    try:
        import redis
        r = redis.from_url(settings.CELERY_BROKER_URL)
        r.ping()
        print(f"  Redis reachable: YES  ({settings.CELERY_BROKER_URL})")
        # Celery default queue list keys
        for q in ["pipeline", "default", "celery"]:
            depth = r.llen(q)
            print(f"  Queue '{q}': {depth} pending task(s)")
    except Exception as e:
        print(f"  Redis ERROR: {e}")

    print()
    print("=" * 60)
    print("2) DOCUMENTS IN DATABASE")
    print("=" * 60)
    db = SyncSessionLocal()
    try:
        docs = db.query(Document).order_by(Document.created_at.desc()).limit(5).all()
        if not docs:
            print("  No documents found in DB.")
            print("  => Upload never reached the backend, OR backend couldn't write.")
        for d in docs:
            ws = db.query(WorkflowState).filter(WorkflowState.document_id == d.id).first()
            print(f"  {d.document_id}  status={d.status}")
            print(f"      file={d.original_filename}")
            if ws:
                print(f"      stage={ws.current_stage}  agent={ws.current_agent}  progress={ws.progress_percent}%")
                if ws.error_message:
                    print(f"      ERROR: {ws.error_message}")
            else:
                print("      (no workflow state — pipeline never started)")

        # Show last few audit errors
        print()
        print("  Recent audit actions:")
        logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(8).all()
        for l in logs:
            print(f"    [{l.timestamp:%H:%M:%S}] {l.action} ({l.agent or '-'})")
    finally:
        db.close()

    print()
    print("=" * 60)
    print("INTERPRETATION")
    print("=" * 60)
    print("  - 'pipeline' queue > 0 and no audit actions => Celery WORKER not running.")
    print("  - No documents in DB => upload didn't reach backend (check uvicorn).")
    print("  - Document exists, status=PROCESSING, has stages => it IS working; check Documents page.")
    print("  - status=FAILED with ERROR => paste that error.")


if __name__ == "__main__":
    main()
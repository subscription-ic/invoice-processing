"""
Diagnose and fix login.
Usage: python seed/fix_login.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_candidates = ["/app", str(Path(__file__).parent.parent / "backend")]
for _c in _candidates:
    if Path(_c, "app", "core").exists():
        sys.path.insert(0, _c)
        break

from app.core.database import SyncSessionLocal
from app.core.security import hash_password, verify_password
from app.models.models import User, UserRole


def main():
    db = SyncSessionLocal()
    try:
        users = db.query(User).all()
        print(f"\n=== {len(users)} users in database ===")
        for u in users:
            print(f"  email={u.email!r}  role={u.role}  active={u.is_active}")

        # Force-create/reset admin/admin
        admin = db.query(User).filter(User.email == "admin").first()
        if not admin:
            admin = User(email="admin", name="Administrator", role=UserRole.ADMIN,
                         department="IT", is_active=True, is_superuser=True,
                         hashed_password=hash_password("admin"))
            db.add(admin)
            print("\nCreated user 'admin'")
        else:
            admin.hashed_password = hash_password("admin")
            admin.is_active = True
            print("\nReset user 'admin'")

        # Reset seeded admin
        seeded = db.query(User).filter(User.email == "admin@company.com").first()
        if seeded:
            seeded.hashed_password = hash_password("password123")
            seeded.is_active = True

        db.commit()

        # Verify round-trip
        db.refresh(admin)
        ok = verify_password("admin", admin.hashed_password)
        print(f"\nVerification test for admin/admin: {'PASS ✓' if ok else 'FAIL ✗'}")

        if seeded:
            db.refresh(seeded)
            ok2 = verify_password("password123", seeded.hashed_password)
            print(f"Verification test for admin@company.com/password123: {'PASS ✓' if ok2 else 'FAIL ✗'}")

        print("\nLog in with:  admin / admin")
    finally:
        db.close()


if __name__ == "__main__":
    main()
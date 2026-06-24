"""
Seed the governance data needed for the Approval Center to work:
  - Approver users (AP Team, Approver, Finance, CFO/Admin) with known passwords
  - Approval rules (amount-tiered matrix)

Run from backend/:  python ..\seed\seed_governance.py
After this, documents that complete validation will route to PENDING_APPROVAL
and appear on the Approval Center for the relevant approver.
"""
from __future__ import annotations

import sys
from pathlib import Path
from decimal import Decimal

_candidates = ["/app", str(Path(__file__).parent.parent / "backend")]
for _c in _candidates:
    if Path(_c, "app", "core").exists():
        sys.path.insert(0, _c)
        break

from app.core.database import SyncSessionLocal
from app.core.security import hash_password
from app.models.models import User, ApprovalRule, UserRole


USERS = [
    ("admin@company.com", "Administrator", UserRole.ADMIN, "Finance"),
    ("ap@company.com", "AP Clerk", UserRole.AP_TEAM, "Finance"),
    ("approver@company.com", "Department Approver", UserRole.APPROVER, "Operations"),
    ("finance@company.com", "Finance Controller", UserRole.FINANCE, "Finance"),
]


def main():
    db = SyncSessionLocal()
    try:
        # 1. Users (password = password123; 'admin' user also kept by fix_login)
        users = {}
        for email, name, role, dept in USERS:
            u = db.query(User).filter(User.email == email).first()
            if not u:
                u = User(email=email, name=name, hashed_password=hash_password("password123"),
                         role=role, department=dept, is_active=True)
                db.add(u); db.flush()
                print(f"  created user {email} ({role})")
            else:
                u.role = role
                u.is_active = True
            users[role] = u
        db.commit()

        ap = users[UserRole.AP_TEAM]
        approver = users[UserRole.APPROVER]
        finance = users[UserRole.FINANCE]
        admin = users[UserRole.ADMIN]

        # 2. Approval rules (clear existing, recreate tiers)
        db.query(ApprovalRule).delete()
        db.flush()

        rules = [
            {
                "name": "Small Amount — Single Approval (<= 25k)",
                "business_profile": None, "amount_min": Decimal("0"), "amount_max": Decimal("25000"),
                "priority": 10,
                "approval_matrix": [
                    {"level": 1, "user_id": str(ap.id), "role": "AP_TEAM", "escalation_hours": 8},
                ],
            },
            {
                "name": "Medium Amount — Two Level (25k–2L)",
                "business_profile": None, "amount_min": Decimal("25001"), "amount_max": Decimal("200000"),
                "priority": 20,
                "approval_matrix": [
                    {"level": 1, "user_id": str(ap.id), "role": "AP_TEAM", "escalation_hours": 8},
                    {"level": 2, "user_id": str(approver.id), "role": "APPROVER", "escalation_hours": 16},
                ],
            },
            {
                "name": "Large Amount — Three Level (2L–10L)",
                "business_profile": None, "amount_min": Decimal("200001"), "amount_max": Decimal("1000000"),
                "priority": 30,
                "approval_matrix": [
                    {"level": 1, "user_id": str(ap.id), "role": "AP_TEAM", "escalation_hours": 8},
                    {"level": 2, "user_id": str(approver.id), "role": "APPROVER", "escalation_hours": 16},
                    {"level": 3, "user_id": str(finance.id), "role": "FINANCE", "escalation_hours": 24},
                ],
            },
            {
                "name": "High Value — CFO Approval (>10L)",
                "business_profile": None, "amount_min": Decimal("1000001"), "amount_max": None,
                "priority": 40,
                "approval_matrix": [
                    {"level": 1, "user_id": str(ap.id), "role": "AP_TEAM", "escalation_hours": 4},
                    {"level": 2, "user_id": str(approver.id), "role": "APPROVER", "escalation_hours": 8},
                    {"level": 3, "user_id": str(finance.id), "role": "FINANCE", "escalation_hours": 12},
                    {"level": 4, "user_id": str(admin.id), "role": "ADMIN", "escalation_hours": 24},
                ],
            },
        ]
        for r in rules:
            db.add(ApprovalRule(**r))
        db.commit()
        print(f"  created {len(rules)} approval rules")
        print("\n✅ Governance seeded. New documents will now route to the Approval Center.")
        print("   Approver logins (all password123): ap@company.com, approver@company.com, finance@company.com")
    except Exception as e:
        db.rollback()
        print(f"❌ Failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
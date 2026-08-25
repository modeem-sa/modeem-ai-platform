"""Dev seed script — creates two tenants and one admin user each.

Usage (from modeem-ai-platform/apps/api/):
    DATABASE_URL=$DATABASE_URL SESSION_SECRET=$SESSION_SECRET python seed.py

Seeded credentials
------------------
Tenant 1 — Acme Corp (code: acme)
  email: admin@acme.com   password: Dev@2025!

Tenant 2 — Beta Ltd (code: beta)
  email: admin@beta.com   password: Dev@2025!

Idempotent: running twice skips rows that already exist.
"""

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Ensure the API package is importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).parent))

from app.core.paths import ensure_shared_packages_importable

ensure_shared_packages_importable()

from app.core.security import hash_password
from app.db.base import get_session_factory
from app.models import Tenant, TenantMembership, User

TENANTS = [
    {"name": "Acme Corp", "code": "acme"},
    {"name": "Beta Ltd", "code": "beta"},
]

USERS = [
    {"email": "admin@acme.com", "tenant_code": "acme", "display_name": "Acme Admin", "role": "admin"},
    {"email": "admin@beta.com", "tenant_code": "beta", "display_name": "Beta Admin", "role": "admin"},
]

DEV_PASSWORD = "Dev@2025!"


def seed() -> None:
    Session = get_session_factory()
    now = datetime.now(UTC)

    with Session() as db:
        tenant_map: dict[str, uuid.UUID] = {}

        # ── Tenants ─────────────────────────────────────────────────────────
        for t in TENANTS:
            existing = db.query(Tenant).filter_by(code=t["code"]).first()
            if existing:
                print(f"  [skip] Tenant '{t['code']}' already exists.")
                tenant_map[t["code"]] = existing.id
            else:
                tenant = Tenant(name=t["name"], code=t["code"], created_at=now, updated_at=now)
                db.add(tenant)
                db.flush()
                tenant_map[t["code"]] = tenant.id
                print(f"  [seed] Created tenant '{t['code']}' (id={tenant.id})")

        # ── Users ────────────────────────────────────────────────────────────
        hashed = hash_password(DEV_PASSWORD)
        for u in USERS:
            existing = db.query(User).filter_by(email=u["email"]).first()
            if existing:
                print(f"  [skip] User '{u['email']}' already exists.")
                user = existing
            else:
                user = User(
                    email=u["email"],
                    full_name=u["display_name"],
                    password_hash=hashed,
                    created_at=now,
                    updated_at=now,
                )
                db.add(user)
                db.flush()
                print(f"  [seed] Created user '{u['email']}'")

            tenant_id = tenant_map[u["tenant_code"]]
            membership = (
                db.query(TenantMembership)
                .filter_by(user_id=user.id, tenant_id=tenant_id)
                .first()
            )
            if membership:
                print(f"  [skip] Membership {u['email']} → {u['tenant_code']} exists.")
            else:
                db.add(
                    TenantMembership(
                        user_id=user.id,
                        tenant_id=tenant_id,
                        role=u["role"],
                    )
                )
                print(f"  [seed] Membership {u['email']} → {u['tenant_code']} ({u['role']})")

        db.commit()

    print("\nSeed complete.")
    print(f"  Tenant 1 — admin@acme.com / {DEV_PASSWORD}")
    print(f"  Tenant 2 — admin@beta.com / {DEV_PASSWORD}")


if __name__ == "__main__":
    seed()

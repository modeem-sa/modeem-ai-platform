"""Idempotent bootstrap of the first administrator (development helper).

Usage:
    BOOTSTRAP_ADMIN_EMAIL=... BOOTSTRAP_ADMIN_PASSWORD=... BOOTSTRAP_TENANT_NAME=... \
        python -m app.bootstrap_admin

Creates (if missing): the tenant, the admin user (superuser), and an
"owner" membership. Running it again is a no-op. Never commit real
credentials; values come from environment variables only.
"""

from app.core.paths import ensure_shared_packages_importable

ensure_shared_packages_importable()

import re
import sys

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import get_session_factory
from app.models import Tenant, TenantMembership, User
from app.models.user import normalize_email
from app.services.audit import record_audit


def _tenant_code(name: str) -> str:
    code = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return code or "default"


def bootstrap() -> int:
    settings = get_settings()
    email = normalize_email(settings.bootstrap_admin_email or "")
    password = settings.bootstrap_admin_password or ""
    tenant_name = (settings.bootstrap_tenant_name or "").strip()

    if not email or not password or not tenant_name:
        print(
            "BOOTSTRAP_ADMIN_EMAIL, BOOTSTRAP_ADMIN_PASSWORD and "
            "BOOTSTRAP_TENANT_NAME are required."
        )
        return 1

    session_factory = get_session_factory()
    db = session_factory()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == tenant_name).one_or_none()
        if tenant is None:
            tenant = Tenant(name=tenant_name, code=_tenant_code(tenant_name))
            db.add(tenant)
            db.flush()

        user = db.query(User).filter(User.email == email).one_or_none()
        created_user = False
        if user is None:
            user = User(
                email=email,
                full_name="Administrator",
                password_hash=hash_password(password),
                is_active=True,
                is_superuser=True,
            )
            db.add(user)
            db.flush()
            created_user = True

        membership = (
            db.query(TenantMembership)
            .filter(
                TenantMembership.tenant_id == tenant.id,
                TenantMembership.user_id == user.id,
            )
            .one_or_none()
        )
        if membership is None:
            membership = TenantMembership(
                tenant_id=tenant.id, user_id=user.id, role="owner", is_active=True
            )
            db.add(membership)

        if created_user:
            record_audit(
                db,
                action="auth.bootstrap_admin_created",
                actor_type="system",
                actor_id="bootstrap",
                tenant_id=tenant.id,
                metadata={"email": email},
            )

        db.commit()
        print(
            f"Bootstrap complete: tenant='{tenant.name}' user='{user.email}' "
            f"(created_user={created_user})"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(bootstrap())

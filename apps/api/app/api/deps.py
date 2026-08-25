"""Reusable FastAPI dependencies for DB sessions, auth, and tenant context."""

import uuid
from collections.abc import Callable, Generator
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import SESSION_COOKIE_NAME, decode_session_token
from app.db.base import get_session_factory
from app.models import Tenant, TenantMembership, User

_session_factory = None
import hmac
import os
from typing import Annotated


def get_db() -> Generator[Session, None, None]:
    global _session_factory
    if _session_factory is None:
        _session_factory = get_session_factory()
    db = _session_factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@dataclass
class TenantContext:
    tenant: Tenant
    membership: TenantMembership | None  # None only for explicit superuser access
    role: str


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
    )


def get_session_payload(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise _unauthorized()
    payload = decode_session_token(token)
    if payload is None or "sub" not in payload:
        raise _unauthorized()
    return payload


def get_current_user(
    payload: dict = Depends(get_session_payload),
    db: Session = Depends(get_db),
) -> User:
    try:
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, KeyError) as exc:
        raise _unauthorized() from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized()
    return user


def get_active_memberships(db: Session, user: User) -> list[TenantMembership]:
    return list(
        db.query(TenantMembership)
        .filter(
            TenantMembership.user_id == user.id,
            TenantMembership.is_active.is_(True),
        )
        .all()
    )


def resolve_tenant_context(
    db: Session, user: User, requested_tenant_id: uuid.UUID | None
) -> TenantContext:
    """Validate and resolve the current tenant for a user.

    A client-supplied tenant id is NEVER trusted: membership is always
    re-checked in the database. Superuser access without membership is
    explicit (role "superuser") so it stays auditable.
    """
    memberships = get_active_memberships(db, user)

    membership: TenantMembership | None = None
    if requested_tenant_id is not None:
        membership = next(
            (m for m in memberships if m.tenant_id == requested_tenant_id), None
        )
        if membership is None and not user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No active membership for this tenant",
            )
    elif len(memberships) == 1:
        # Exactly one tenant: select automatically.
        membership = memberships[0]
    elif len(memberships) > 1:
        # Never pick an arbitrary tenant (e.g. database row order). The user
        # must select explicitly via POST /api/v1/auth/tenant.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Tenant selection required"
        )

    if membership is not None:
        tenant = db.get(Tenant, membership.tenant_id)
        if tenant is None or not tenant.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Tenant is not active"
            )
        return TenantContext(tenant=tenant, membership=membership, role=membership.role)

    if user.is_superuser and requested_tenant_id is not None:
        tenant = db.get(Tenant, requested_tenant_id)
        if tenant is None or not tenant.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Tenant is not active"
            )
        return TenantContext(tenant=tenant, membership=None, role="superuser")

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="No tenant context available"
    )


def get_current_tenant(
    payload: dict = Depends(get_session_payload),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenantContext:
    requested: uuid.UUID | None = None
    tid = payload.get("tid")
    if tid:
        try:
            requested = uuid.UUID(tid)
        except ValueError as exc:
            raise _unauthorized() from exc
    return resolve_tenant_context(db, user, requested)


def require_role(*roles: str) -> Callable:
    """Dependency factory: allow only members whose role is in `roles`.

    Explicit superuser access (role "superuser") is allowed and auditable.
    """

    def _checker(ctx: TenantContext = Depends(get_current_tenant)) -> TenantContext:
        if ctx.role == "superuser":
            return ctx
        if ctx.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role"
            )
        return ctx

    return _checker

def require_internal_auth(
    x_internal_token: Annotated[str | None, Header()] = None,
) -> None:
    """Verify X-Internal-Token matches SESSION_SECRET using constant-time comparison."""
    secret = os.environ.get("SESSION_SECRET", "")
    if not secret:
        raise HTTPException(status_code=500, detail="Server misconfigured: SESSION_SECRET missing")
    if x_internal_token is None or not hmac.compare_digest(x_internal_token, secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

def get_tenant_id(
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> uuid.UUID:
    """Extract and validate the X-Tenant-ID header set by the server-side proxy."""
    if x_tenant_id is None:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-Tenant-ID: must be a UUID")

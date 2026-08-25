"""FastAPI dependency-injection helpers for DB sessions, auth, and tenant scoping."""

from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core import security
from app.db.base import get_session_factory
from app.models.tenant import Tenant
from app.models.user import User

# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------


def get_db() -> Generator[Session, None, None]:
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Decode the access_token cookie and return the authenticated User."""
    payload = security.decode_token_from_request(request, cookie_name="access_token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


# ---------------------------------------------------------------------------
# Tenant scoping
# ---------------------------------------------------------------------------


def get_tenant(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Tenant:
    """Return the Tenant for the authenticated user — every data query is scoped to this."""
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None or not tenant.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant not found or inactive")
    return tenant

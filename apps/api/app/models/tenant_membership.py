"""TenantMembership — links users to tenants with a role."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base

ALLOWED_ROLES = ("owner", "admin", "manager", "member", "viewer")

ROLE_CHECK_SQL = "role IN ('owner', 'admin', 'manager', 'member', 'viewer')"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TenantMembership(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
        CheckConstraint(ROLE_CHECK_SQL, name="ck_tenant_memberships_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    @validates("role")
    def _validate_role(self, _key: str, value: str) -> str:
        if value not in ALLOWED_ROLES:
            raise ValueError(f"Invalid role: {value!r}. Allowed: {ALLOWED_ROLES}")
        return value

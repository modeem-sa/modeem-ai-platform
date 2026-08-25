"""Connection — tenant-scoped external system configuration (Phase 2B).

Secrets live ONLY in `encrypted_credentials` (AES-256-GCM, see
app/services/credential_crypto.py). Non-secret metadata (base_url,
database_name, username) may be stored in clear text for display.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ALLOWED_PROVIDERS = ("odoo",)
ALLOWED_STATUSES = ("configured", "disabled")
ALLOWED_AUTH_MODES = ("auto", "password", "api_key")
ALLOWED_EDITIONS = ("community", "enterprise", "unknown")
ALLOWED_TRANSPORTS = ("xmlrpc", "json2", "unknown")

PROVIDER_CHECK_SQL = "provider IN ('odoo')"
STATUS_CHECK_SQL = "status IN ('configured', 'disabled')"
AUTH_MODE_CHECK_SQL = "auth_mode IN ('auto', 'password', 'api_key')"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_connections_tenant_name"),
        CheckConstraint(PROVIDER_CHECK_SQL, name="ck_connections_provider"),
        CheckConstraint(STATUS_CHECK_SQL, name="ck_connections_status"),
        CheckConstraint(AUTH_MODE_CHECK_SQL, name="ck_connections_auth_mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    database_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    username: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Secret payload: nonce || AES-256-GCM ciphertext. Never returned by APIs.
    encrypted_credentials: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encryption_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Phase 2C: authentication mode + safe detected metadata (never secrets).
    auth_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="auto", server_default="auto"
    )
    detected_odoo_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detected_odoo_major: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detected_edition: Mapped[str | None] = mapped_column(String(16), nullable=True)
    selected_transport: Mapped[str | None] = mapped_column(String(16), nullable=True)
    capabilities_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_test_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="configured")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_test_status: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

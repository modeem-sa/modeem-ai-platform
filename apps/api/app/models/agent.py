"""Persistent, request-bound internal AI workbench records."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active','completed','failed')", name="ck_agent_sessions_status"),
        UniqueConstraint(
            "tenant_id",
            "service_request_id",
            "employee_user_id",
            name="uq_agent_sessions_tenant_request_employee",
        ),
        Index("ix_agent_sessions_tenant_request", "tenant_id", "service_request_id"),
        Index("ix_agent_sessions_employee_status", "employee_user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    service_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False
    )
    employee_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("connections.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    provider_model: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    prompt_sha256: Mapped[str | None] = mapped_column(String(64))
    latest_analysis_json: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','system')", name="ck_agent_messages_role"),
        Index("ix_agent_messages_session_created", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
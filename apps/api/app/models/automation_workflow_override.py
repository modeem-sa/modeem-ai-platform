"""Tenant overrides for the fixed automation catalogue."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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


class AutomationWorkflowOverride(Base):
    __tablename__ = "automation_workflow_overrides"
    __table_args__ = (
        UniqueConstraint("tenant_id", "workflow_key", name="uq_automation_workflow_override_tenant_key"),
        CheckConstraint("version >= 1", name="ck_automation_workflow_override_version"),
        CheckConstraint("length(workflow_key) BETWEEN 1 AND 128", name="ck_automation_workflow_override_key"),
        CheckConstraint("length(step_modes_json) BETWEEN 2 AND 10000", name="ck_automation_workflow_override_modes"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_key: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    step_modes_json: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
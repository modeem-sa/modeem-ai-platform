"""Tenant-scoped work item shown on the shared-services operations board."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OperationsTask(Base):
    __tablename__ = "operations_tasks"
    __table_args__ = (
        CheckConstraint(
            "work_type IN ('administrative', 'financial')",
            name="ck_operations_tasks_work_type",
        ),
        CheckConstraint(
            "status IN ('upcoming', 'overdue', 'awaiting_approval', "
            "'needs_intervention', 'completed')",
            name="ck_operations_tasks_status",
        ),
        CheckConstraint(
            "priority IN ('urgent', 'high', 'normal')",
            name="ck_operations_tasks_priority",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    work_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    assignee_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
"""Tenant-scoped operations tasks and their append-only lifecycle history."""

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
    Uuid,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base

TASK_CATEGORIES = ("administrative", "financial")
TASK_PRIORITIES = ("low", "medium", "high", "urgent")
TASK_STATUSES = (
    "pending",
    "in_progress",
    "completed",
    "submitted_for_approval",
    "approved",
    "rejected",
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OperationTask(Base):
    __tablename__ = "operation_tasks"
    __table_args__ = (
        CheckConstraint(
            "category IN ('administrative', 'financial')",
            name="ck_operation_tasks_category",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')",
            name="ck_operation_tasks_priority",
        ),
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', "
            "'submitted_for_approval', 'approved', 'rejected')",
            name="ck_operation_tasks_status",
        ),
        CheckConstraint("version >= 1", name="ck_operation_tasks_version"),
        Index("ix_operation_tasks_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    @validates("category", "priority", "status")
    def _validate_choice(self, key: str, value: str) -> str:
        allowed = {
            "category": TASK_CATEGORIES,
            "priority": TASK_PRIORITIES,
            "status": TASK_STATUSES,
        }[key]
        if value not in allowed:
            raise ValueError(f"Invalid {key}: {value!r}")
        return value

    @validates("title")
    def _validate_title(self, _key: str, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 255:
            raise ValueError("Task title must be between 1 and 255 characters")
        return value

    @validates("description", "decision_note")
    def _validate_text(self, key: str, value: str | None) -> str | None:
        maximum = 10000 if key == "description" else 2000
        if value is not None and len(value) > maximum:
            raise ValueError(f"Task {key} must not exceed {maximum} characters")
        return value


class OperationTaskHistory(Base):
    """An append-only record of each task lifecycle event."""

    __tablename__ = "operation_task_history"
    __table_args__ = (
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('pending', 'in_progress', "
            "'completed', 'submitted_for_approval', 'approved', 'rejected')",
            name="ck_operation_task_history_from_status",
        ),
        CheckConstraint(
            "to_status IN ('pending', 'in_progress', 'completed', "
            "'submitted_for_approval', 'approved', 'rejected')",
            name="ck_operation_task_history_to_status",
        ),
        CheckConstraint("version >= 1", name="ck_operation_task_history_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("operation_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


@event.listens_for(OperationTaskHistory, "before_update")
def _history_cannot_change(*_args) -> None:
    raise ValueError("Operation task history is immutable")


@event.listens_for(OperationTaskHistory, "before_delete")
def _history_cannot_delete(*_args) -> None:
    raise ValueError("Operation task history is immutable")
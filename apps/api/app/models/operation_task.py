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
    UniqueConstraint,
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
        UniqueConstraint(
            "tenant_id", "source_connection_id", "source_record_id", "source_signal",
            name="uq_operation_tasks_odoo_signal",
        ),
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
    # Server-owned provenance for generated work.  Manual tasks leave these null.
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("connections.id", ondelete="SET NULL"), nullable=True
    )
    source_record_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_signal: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_sync_state: Mapped[str | None] = mapped_column(String(32), nullable=True)

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
        Uuid, ForeignKey("operation_tasks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
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


class OperationAction(Base):
    """One current, externally executable proposal per task."""

    __tablename__ = "operation_actions"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_operation_actions_task"),
        CheckConstraint(
            "status IN ('proposed', 'awaiting_approval', 'approved', 'queued', "
            "'executing', 'verifying', 'succeeded', 'failed')",
            name="ck_operation_actions_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("operation_tasks.id", ondelete="CASCADE"), nullable=False)
    proposal_json: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_marker: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_activity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class OperationActionHistory(Base):
    """Append-only, server-authored action lifecycle evidence."""

    __tablename__ = "operation_action_history"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_operation_action_history_version"),
        CheckConstraint(
            "actor_type IN ('user', 'worker', 'system')",
            name="ck_operation_action_history_actor_type",
        ),
        CheckConstraint(
            "event IN ('generated', 'regenerated', 'submitted', 'rejected', "
            "'approved', 'retry_queued', 'executing', 'succeeded', 'failed')",
            name="ck_operation_action_history_event",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    action_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("operation_actions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("operation_tasks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    proposal_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


@event.listens_for(OperationActionHistory, "before_update")
def _action_history_cannot_change(*_args) -> None:
    raise ValueError("Operation action history is immutable")


@event.listens_for(OperationActionHistory, "before_delete")
def _action_history_cannot_delete(*_args) -> None:
    raise ValueError("Operation action history is immutable")


class RecurringTaskTemplate(Base):
    __tablename__ = "recurring_task_templates"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="administrative")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    frequency: Mapped[str] = mapped_column(String(16), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class RecurringTaskOccurrence(Base):
    __tablename__ = "recurring_task_occurrences"
    __table_args__ = (UniqueConstraint("template_id", "occurrence_date", name="uq_recurring_task_occurrence"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("recurring_task_templates.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("operation_tasks.id", ondelete="CASCADE"), nullable=False)
    occurrence_date: Mapped[str] = mapped_column(String(10), nullable=False)
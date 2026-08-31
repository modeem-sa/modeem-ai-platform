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

TASK_CATEGORIES = ("administrative", "financial", "human_resources")
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
            "category IN ('administrative', 'financial', 'human_resources')",
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
    procedure_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    workflow_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    workflow_config_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
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


class CollectionMessage(Base):
    """A fixed-channel customer collection message with an immutable approval."""

    __tablename__ = "invoice_collection_messages"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_invoice_collection_messages_task"),
        UniqueConstraint("idempotency_marker", name="uq_invoice_collection_messages_marker"),
        CheckConstraint(
            "status IN ('draft', 'awaiting_approval', 'queued', 'sending', "
            "'verifying', 'succeeded', 'failed')",
            name="ck_invoice_collection_messages_status",
        ),
        CheckConstraint("draft_version >= 1", name="ck_invoice_collection_messages_draft_version"),
        CheckConstraint("source_version >= 1", name="ck_invoice_collection_messages_source_version"),
        CheckConstraint("version >= 1", name="ck_invoice_collection_messages_version"),
        CheckConstraint("attempt_count >= 0 AND attempt_count <= 3", name="ck_invoice_collection_messages_attempts"),
        CheckConstraint(
            "length(draft_content) BETWEEN 1 AND 1000",
            name="ck_invoice_collection_messages_draft_length",
        ),
        CheckConstraint(
            "length(draft_hash) = 64 AND "
            "length(source_hash) = 64 AND "
            "(approved_hash IS NULL OR length(approved_hash) = 64) AND "
            "(approved_source_hash IS NULL OR length(approved_source_hash) = 64)",
            name="ck_invoice_collection_messages_hash_lengths",
        ),
        CheckConstraint(
            "approved_draft_version IS NULL OR approved_draft_version >= 1",
            name="ck_invoice_collection_messages_approved_version",
        ),
        CheckConstraint(
            "approved_source_version IS NULL OR approved_source_version >= 1",
            name="ck_invoice_collection_messages_approved_source_version",
        ),
        CheckConstraint(
            "external_message_id IS NULL OR external_message_id > 0",
            name="ck_invoice_collection_messages_receipt",
        ),
        CheckConstraint(
            "source_partner_id > 0 AND (approved_partner_id IS NULL OR approved_partner_id > 0)",
            name="ck_invoice_collection_messages_partner_ids",
        ),
        CheckConstraint(
            "(approved_content IS NULL AND approved_hash IS NULL AND approved_draft_version IS NULL "
            "AND approved_source_hash IS NULL AND approved_source_version IS NULL "
            "AND approved_partner_id IS NULL "
            "AND approved_by_user_id IS NULL AND approved_at IS NULL) OR "
            "(approved_content IS NOT NULL AND approved_hash IS NOT NULL "
            "AND approved_draft_version IS NOT NULL AND approved_source_hash IS NOT NULL "
            "AND approved_source_version IS NOT NULL AND approved_partner_id IS NOT NULL "
            "AND approved_by_user_id IS NOT NULL "
            "AND approved_at IS NOT NULL)",
            name="ck_invoice_collection_messages_approval_complete",
        ),
        Index(
            "ix_invoice_collection_messages_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("operation_tasks.id", ondelete="CASCADE"), nullable=False
    )
    draft_content: Mapped[str] = mapped_column(Text, nullable=False)
    draft_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_partner_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_draft_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_source_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_partner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_marker: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


_APPROVED_MESSAGE_FIELDS = (
    "approved_content",
    "approved_hash",
    "approved_draft_version",
    "approved_source_hash",
    "approved_source_version",
    "approved_partner_id",
    "approved_by_user_id",
    "approved_at",
)


@event.listens_for(CollectionMessage, "before_update")
def _approved_message_cannot_change(_mapper, _connection, target) -> None:
    from sqlalchemy import inspect

    state = inspect(target)
    for name in _APPROVED_MESSAGE_FIELDS:
        history = state.attrs[name].history
        if history.deleted and history.deleted[0] is not None:
            raise ValueError("Approved collection message is immutable")


class CollectionMessageEvent(Base):
    """Append-only evidence for generation, review, approval, and delivery."""

    __tablename__ = "invoice_collection_message_events"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_invoice_collection_message_events_version"),
        CheckConstraint(
            "length(content_hash) = 64",
            name="ck_invoice_collection_message_events_hash_length",
        ),
        CheckConstraint(
            "actor_type IN ('user', 'worker', 'system')",
            name="ck_invoice_collection_message_events_actor_type",
        ),
        CheckConstraint(
            "event IN ('generated', 'regenerated', 'submitted', 'rejected', "
            "'approved', 'policy_checked', 'policy_blocked', 'retry_queued', 'sending', "
            "'sent', 'verifying', 'verified', 'succeeded', 'failed')",
            name="ck_invoice_collection_message_events_event",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("invoice_collection_messages.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("operation_tasks.id", ondelete="RESTRICT"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


@event.listens_for(CollectionMessageEvent, "before_update")
@event.listens_for(CollectionMessageEvent, "before_delete")
def _message_event_cannot_change(*_args) -> None:
    raise ValueError("Collection message events are immutable")


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
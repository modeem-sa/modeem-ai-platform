"""Customer shared-service requests and immutable evidence."""
import uuid
from datetime import UTC, datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, event
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

def _now() -> datetime: return datetime.now(UTC)

class ServiceRequest(Base):
    __tablename__ = "service_requests"
    __table_args__ = (
        CheckConstraint("priority IN ('low','medium','high','urgent')", name="ck_service_requests_priority"),
        CheckConstraint("source IN ('portal','email')", name="ck_service_requests_source"),
        CheckConstraint("status IN ('open','in_progress','waiting_customer','resolved','closed')", name="ck_service_requests_status"),
        CheckConstraint("automation_status IN ('none','queued','running','succeeded','failed')", name="ck_service_requests_automation_status"),
        CheckConstraint("version >= 1", name="ck_service_requests_version"),
        UniqueConstraint("public_reference", name="uq_service_requests_reference"),
        UniqueConstraint("operation_task_id", name="uq_service_requests_operation_task"),
        Index("ix_service_requests_tenant_status", "tenant_id", "status"),
        Index("ix_service_requests_tenant_assignee_status", "tenant_id", "assigned_employee_id", "status"),
        Index("ix_service_requests_tenant_requester", "tenant_id", "requester_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    requester_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    assigned_employee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    requested_module: Mapped[str | None] = mapped_column(String(255))
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="portal")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    installed_modules_json: Mapped[str | None] = mapped_column(Text)
    workflow_key: Mapped[str | None] = mapped_column(String(128))
    workflow_config_version: Mapped[int | None] = mapped_column(Integer)
    operation_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("operation_tasks.id", ondelete="RESTRICT"), nullable=True
    )
    automation_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    automation_result_json: Mapped[str | None] = mapped_column(Text)
    automation_receipt: Mapped[str | None] = mapped_column(String(255))
    automation_error: Mapped[str | None] = mapped_column(Text)
    automation_queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    automation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    automation_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    public_reference: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

class ServiceRequestMessage(Base):
    __tablename__ = "service_request_messages"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("service_requests.id", ondelete="RESTRICT"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

class ServiceRequestAttachment(Base):
    __tablename__ = "service_request_attachments"
    __table_args__ = (
        CheckConstraint("size > 0 AND size <= 10485760", name="ck_service_request_attachments_size"),
        CheckConstraint("length(sha256) = 64", name="ck_service_request_attachments_sha256"),
        Index("ix_service_request_attachments_request_created", "request_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("service_requests.id", ondelete="RESTRICT"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(600), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

class ServiceRequestEvent(Base):
    __tablename__ = "service_request_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("service_requests.id", ondelete="RESTRICT"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

@event.listens_for(ServiceRequestMessage, "before_update")
@event.listens_for(ServiceRequestMessage, "before_delete")
@event.listens_for(ServiceRequestAttachment, "before_update")
@event.listens_for(ServiceRequestAttachment, "before_delete")
@event.listens_for(ServiceRequestEvent, "before_update")
@event.listens_for(ServiceRequestEvent, "before_delete")
def _immutable(*_args): raise ValueError("Service request evidence is immutable")
"""Private, tenant-scoped source invoices and their reviewed accounting data."""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InvoiceDocument(Base):
    __tablename__ = "invoice_documents"
    __table_args__ = (
        CheckConstraint("status IN ('manual_review', 'draft', 'submitted', 'approved', 'rejected', 'failed')",
                        name="ck_invoice_documents_status"),
        CheckConstraint("version >= 1", name="ck_invoice_documents_version"),
        CheckConstraint("file_size > 0 AND file_size <= 8388608", name="ck_invoice_documents_file_size"),
        CheckConstraint("length(sha256) = 64", name="ck_invoice_documents_sha256"),
        Index("ix_invoice_documents_tenant_status", "tenant_id", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"),
                                                   nullable=False, index=True)
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"),
                                                            nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="manual_review")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    invoice_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    partner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    lines_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("connections.id", ondelete="RESTRICT"))
    idempotency_marker: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    odoo_move_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    odoo_attachment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(64))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
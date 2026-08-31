"""Tenant-scoped content manager drafts and their revisions."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ContentDocument(Base):
    __tablename__ = "content_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    original_request: Mapped[str] = mapped_column(Text, nullable=False)
    current_document: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latest_correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class ContentDocumentRevision(Base):
    __tablename__ = "content_document_revisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    provided_fields: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    conversation_messages: Mapped[list[dict[str, str]] | None] = mapped_column(
        JSON, nullable=True
    )
    ui_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    document: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    document_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
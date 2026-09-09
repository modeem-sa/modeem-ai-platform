"""Add private PDF invoice document records.

Revision ID: 0020
Revises: 0019
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "invoice_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False, unique=True),
        sa.Column("content_type", sa.String(64), nullable=False), sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False), sa.Column("extracted_text", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("invoice_type", sa.String(16)), sa.Column("partner_id", sa.Integer()),
        sa.Column("invoice_date", sa.Date()), sa.Column("due_date", sa.Date()), sa.Column("currency_id", sa.Integer()),
        sa.Column("reference", sa.String(255)), sa.Column("notes", sa.Text()), sa.Column("lines_json", sa.Text()),
        sa.Column("approved_hash", sa.String(64)), sa.Column("approved_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("approved_at", sa.DateTime(timezone=True)), sa.Column("connection_id", sa.Uuid(), sa.ForeignKey("connections.id", ondelete="RESTRICT")),
        sa.Column("idempotency_marker", sa.String(64), nullable=False, unique=True),
        sa.Column("odoo_move_id", sa.Integer()), sa.Column("odoo_attachment_id", sa.Integer()), sa.Column("error", sa.String(64)), sa.Column("verified_at", sa.DateTime(timezone=True)), sa.Column("rejection_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('manual_review', 'draft', 'submitted', 'approved', 'rejected', 'failed')", name="ck_invoice_documents_status"),
        sa.CheckConstraint("version >= 1", name="ck_invoice_documents_version"),
        sa.CheckConstraint("file_size > 0 AND file_size <= 8388608", name="ck_invoice_documents_file_size"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_invoice_documents_sha256"),
    )
    op.create_index("ix_invoice_documents_tenant_status", "invoice_documents", ["tenant_id", "status"])
    op.create_index("ix_invoice_documents_tenant_id", "invoice_documents", ["tenant_id"])

def downgrade() -> None:
    op.drop_table("invoice_documents")
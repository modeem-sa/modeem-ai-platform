"""Add tenant-scoped content manager documents and revisions.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Older installations may have received these tables through the 0008
    # convergence step when revision 0007 meant operation tasks.
    if "content_documents" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "content_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("original_request", sa.Text(), nullable=False),
        sa.Column("current_document", sa.Text(), nullable=True),
        sa.Column("document_type", sa.String(length=128), nullable=True),
        sa.Column("latest_correction", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_content_documents_tenant_id", "content_documents", ["tenant_id"])
    op.create_index(
        "ix_content_documents_created_by_user_id", "content_documents", ["created_by_user_id"]
    )

    op.create_table(
        "content_document_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("content_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("provided_fields", sa.JSON(), nullable=True),
        sa.Column("conversation_messages", sa.JSON(), nullable=True),
        sa.Column("ui_config", sa.JSON(), nullable=True),
        sa.Column("document", sa.Text(), nullable=True),
        sa.Column("document_type", sa.String(length=128), nullable=True),
        sa.Column("document_action", sa.String(length=64), nullable=True),
        sa.Column("response_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_content_document_revisions_document_id",
        "content_document_revisions",
        ["document_id"],
    )
    op.create_index(
        "ix_content_document_revisions_tenant_id",
        "content_document_revisions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_content_document_revisions_created_by_user_id",
        "content_document_revisions",
        ["created_by_user_id"],
    )
    op.create_unique_constraint(
        "uq_content_document_revisions_document_number",
        "content_document_revisions",
        ["document_id", "revision_number"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_content_document_revisions_document_number",
        "content_document_revisions",
        type_="unique",
    )
    op.drop_index(
        "ix_content_document_revisions_created_by_user_id",
        table_name="content_document_revisions",
    )
    op.drop_index(
        "ix_content_document_revisions_tenant_id",
        table_name="content_document_revisions",
    )
    op.drop_index(
        "ix_content_document_revisions_document_id",
        table_name="content_document_revisions",
    )
    op.drop_table("content_document_revisions")
    op.drop_index("ix_content_documents_created_by_user_id", table_name="content_documents")
    op.drop_index("ix_content_documents_tenant_id", table_name="content_documents")
    op.drop_table("content_documents")
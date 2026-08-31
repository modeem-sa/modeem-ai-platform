"""Add tenant-scoped operations board tasks.

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operations_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("work_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assignee_name", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("tenant_id", "work_type", "status", "priority", "due_at"):
        op.create_index(f"ix_operations_tasks_{column}", "operations_tasks", [column])


def downgrade() -> None:
    for column in ("due_at", "priority", "status", "work_type", "tenant_id"):
        op.drop_index(f"ix_operations_tasks_{column}", table_name="operations_tasks")
    op.drop_table("operations_tasks")

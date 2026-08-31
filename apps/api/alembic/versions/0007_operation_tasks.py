"""Add tenant-scoped operation tasks and append-only history.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _upgrade_operation_schema() -> None:
    op.create_table(
        "operation_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("assigned_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("category IN ('administrative', 'financial')", name="ck_operation_tasks_category"),
        sa.CheckConstraint("priority IN ('low', 'medium', 'high', 'urgent')", name="ck_operation_tasks_priority"),
        sa.CheckConstraint("status IN ('pending', 'in_progress', 'completed', 'submitted_for_approval', 'approved', 'rejected')", name="ck_operation_tasks_status"),
        sa.CheckConstraint("version >= 1", name="ck_operation_tasks_version"),
    )
    for name, columns in (
        ("ix_operation_tasks_tenant_id", ["tenant_id"]),
        ("ix_operation_tasks_assigned_user_id", ["assigned_user_id"]),
        ("ix_operation_tasks_created_by_user_id", ["created_by_user_id"]),
        ("ix_operation_tasks_tenant_status", ["tenant_id", "status"]),
    ):
        op.create_index(name, "operation_tasks", columns)
    op.create_table(
        "operation_task_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("operation_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("from_status IS NULL OR from_status IN ('pending', 'in_progress', 'completed', 'submitted_for_approval', 'approved', 'rejected')", name="ck_operation_task_history_from_status"),
        sa.CheckConstraint("to_status IN ('pending', 'in_progress', 'completed', 'submitted_for_approval', 'approved', 'rejected')", name="ck_operation_task_history_to_status"),
        sa.CheckConstraint("version >= 1", name="ck_operation_task_history_version"),
    )
    op.create_index("ix_operation_task_history_task_id", "operation_task_history", ["task_id"])
    op.create_index("ix_operation_task_history_tenant_id", "operation_task_history", ["tenant_id"])


def upgrade() -> None:
    """Create operation tables unless a legacy 0007 already created them."""
    if "operation_tasks" not in _table_names():
        _upgrade_operation_schema()


def downgrade() -> None:
    op.drop_index("ix_operation_task_history_tenant_id", table_name="operation_task_history")
    op.drop_index("ix_operation_task_history_task_id", table_name="operation_task_history")
    op.drop_table("operation_task_history")
    op.drop_index("ix_operation_tasks_tenant_status", table_name="operation_tasks")
    op.drop_index("ix_operation_tasks_created_by_user_id", table_name="operation_tasks")
    op.drop_index("ix_operation_tasks_assigned_user_id", table_name="operation_tasks")
    op.drop_index("ix_operation_tasks_tenant_id", table_name="operation_tasks")
    op.drop_table("operation_tasks")
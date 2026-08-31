"""Add lifecycle state to operations board tasks.

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "operations_tasks",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "operations_tasks",
        sa.Column(
            "approval_state",
            sa.String(length=16),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column("operations_tasks", sa.Column("last_note", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_operations_tasks_version", "operations_tasks", "version >= 1"
    )
    op.create_check_constraint(
        "ck_operations_tasks_approval_state",
        "operations_tasks",
        "approval_state IN ('none', 'pending', 'approved', 'rejected')",
    )
    op.alter_column("operations_tasks", "version", server_default=None)
    op.alter_column("operations_tasks", "approval_state", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "ck_operations_tasks_approval_state", "operations_tasks", type_="check"
    )
    op.drop_constraint(
        "ck_operations_tasks_version", "operations_tasks", type_="check"
    )
    op.drop_column("operations_tasks", "last_note")
    op.drop_column("operations_tasks", "approval_state")
    op.drop_column("operations_tasks", "version")
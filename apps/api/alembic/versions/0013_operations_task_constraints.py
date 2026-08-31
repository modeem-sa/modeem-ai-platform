"""Constrain operations board task states to the API contract.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_check_constraints("operations_tasks")
    }
    constraints = (
        (
            "ck_operations_tasks_work_type",
            "work_type IN ('administrative', 'financial')",
        ),
        (
            "ck_operations_tasks_status",
            "status IN ('upcoming', 'overdue', 'awaiting_approval', "
            + "'needs_intervention', 'completed')",
        ),
        (
            "ck_operations_tasks_priority",
            "priority IN ('urgent', 'high', 'normal')",
        ),
    )
    for name, condition in constraints:
        if name not in existing:
            op.create_check_constraint(name, "operations_tasks", condition)


def downgrade() -> None:
    op.drop_constraint(
        "ck_operations_tasks_priority", "operations_tasks", type_="check"
    )
    op.drop_constraint(
        "ck_operations_tasks_status", "operations_tasks", type_="check"
    )
    op.drop_constraint(
        "ck_operations_tasks_work_type", "operations_tasks", type_="check"
    )

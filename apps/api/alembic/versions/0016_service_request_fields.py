"""Add shared-services request details and human resources category.

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "operation_tasks",
        sa.Column("procedure_type", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "operation_tasks",
        sa.Column("request_data_json", sa.Text(), nullable=True),
    )
    op.drop_constraint("ck_operation_tasks_category", "operation_tasks", type_="check")
    op.create_check_constraint(
        "ck_operation_tasks_category",
        "operation_tasks",
        "category IN ('administrative', 'financial', 'human_resources')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_operation_tasks_category", "operation_tasks", type_="check")
    op.execute(
        "UPDATE operation_tasks SET category = 'administrative' "
        "WHERE category = 'human_resources'"
    )
    op.create_check_constraint(
        "ck_operation_tasks_category",
        "operation_tasks",
        "category IN ('administrative', 'financial')",
    )
    op.drop_column("operation_tasks", "request_data_json")
    op.drop_column("operation_tasks", "procedure_type")
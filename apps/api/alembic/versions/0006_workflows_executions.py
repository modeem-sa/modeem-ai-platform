"""Add workflows and executions tables (tenant-scoped dashboard data).

Repairs the post-merge migration chain: the dashboard task shipped
migrations with duplicate revision ids (0002/0003) that conflicted with
the existing chain and were never applied. This single migration creates
the two missing tables to match the current SQLAlchemy models.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-08

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflows_tenant_id", "workflows", ["tenant_id"])

    op.create_table(
        "executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_executions_tenant_id", "executions", ["tenant_id"])
    op.create_index("ix_executions_workflow_id", "executions", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_executions_workflow_id", table_name="executions")
    op.drop_index("ix_executions_tenant_id", table_name="executions")
    op.drop_table("executions")
    op.drop_index("ix_workflows_tenant_id", table_name="workflows")
    op.drop_table("workflows")

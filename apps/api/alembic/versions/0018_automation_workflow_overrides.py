"""Add fixed automation workflow tenant overrides.

Revision ID: 0018
Revises: 0017
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "automation_workflow_overrides",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_key", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("step_modes_json", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "workflow_key", name="uq_automation_workflow_override_tenant_key"),
        sa.CheckConstraint("version >= 1", name="ck_automation_workflow_override_version"),
        sa.CheckConstraint("length(workflow_key) BETWEEN 1 AND 128", name="ck_automation_workflow_override_key"),
        sa.CheckConstraint("length(step_modes_json) BETWEEN 2 AND 10000", name="ck_automation_workflow_override_modes"),
    )
    op.create_index("ix_automation_workflow_overrides_tenant_id", "automation_workflow_overrides", ["tenant_id"])
    op.add_column("operation_actions", sa.Column("workflow_key", sa.String(length=128), nullable=True))
    op.add_column("operation_actions", sa.Column("workflow_config_version", sa.Integer(), nullable=True))

def downgrade() -> None:
    op.drop_column("operation_actions", "workflow_config_version")
    op.drop_column("operation_actions", "workflow_key")
    op.drop_index("ix_automation_workflow_overrides_tenant_id", table_name="automation_workflow_overrides")
    op.drop_table("automation_workflow_overrides")
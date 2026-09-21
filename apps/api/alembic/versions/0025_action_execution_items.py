"""Add bounded execution items for approved Workbench actions."""

import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_action_execution_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_marker", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("external_activity_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(length=128), nullable=True),
        sa.Column("receipt_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["action_id"], ["operation_actions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["operation_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("action_id", "invoice_id", name="uq_action_execution_invoice"),
        sa.UniqueConstraint("idempotency_marker", name="uq_action_execution_marker"),
        sa.CheckConstraint(
            "status IN ('pending','executing','verifying','succeeded','failed')",
            name="ck_action_execution_status",
        ),
        sa.CheckConstraint("attempt_count >= 0 AND attempt_count <= 3",
                           name="ck_action_execution_attempts"),
    )


def downgrade() -> None:
    op.drop_table("operation_action_execution_items")
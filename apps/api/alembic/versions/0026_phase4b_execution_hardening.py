"""Harden Phase 4B execution item bounds and lifecycle evidence."""

import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "operation_actions",
        sa.Column("execution_deadline", sa.String(length=10), nullable=True),
    )
    op.add_column("operation_actions", sa.Column("execution_policy_id", sa.String(64), nullable=True))
    op.add_column("operation_actions", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("operation_actions", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("operation_actions") as batch:
        batch.create_check_constraint(
            "ck_operation_actions_execution_policy",
            "execution_policy_id IS NULL OR execution_policy_id = 'internal_invoice_activity_v1'",
        )
        batch.create_check_constraint(
            "ck_operation_actions_execution_deadline",
            "execution_deadline IS NULL OR length(execution_deadline) = 10",
        )
    with op.batch_alter_table("operation_action_execution_items") as batch:
        batch.create_check_constraint(
            "ck_action_execution_invoice_positive", "invoice_id > 0"
        )
        batch.create_check_constraint(
            "ck_action_execution_external_positive",
            "external_activity_id IS NULL OR external_activity_id > 0",
        )
    # SQLite and PostgreSQL both support replacing this check through the
    # batch helper, keeping the migration usable in the test database.
    with op.batch_alter_table("operation_action_history") as batch:
        batch.drop_constraint("ck_operation_action_history_event", type_="check")
        batch.create_check_constraint(
            "ck_operation_action_history_event",
            "event IN ('generated','regenerated','submitted','rejected',"
            "'approved','queued','retry_queued','execution_started',"
            "'preflight_failed','target_started','target_verified',"
            "'executing','verifying','succeeded','failed')",
        )


def downgrade() -> None:
    with op.batch_alter_table("operation_actions") as batch:
        batch.drop_constraint("ck_operation_actions_execution_deadline", type_="check")
        batch.drop_constraint("ck_operation_actions_execution_policy", type_="check")
    op.drop_column("operation_actions", "execution_deadline")
    op.drop_column("operation_actions", "execution_policy_id")
    op.drop_column("operation_actions", "claimed_at")
    op.drop_column("operation_actions", "lease_expires_at")
    with op.batch_alter_table("operation_action_history") as batch:
        batch.drop_constraint("ck_operation_action_history_event", type_="check")
        batch.create_check_constraint(
            "ck_operation_action_history_event",
            "event IN ('generated','regenerated','submitted','rejected',"
            "'approved','retry_queued','executing','succeeded','failed')",
        )
    with op.batch_alter_table("operation_action_execution_items") as batch:
        batch.drop_constraint("ck_action_execution_external_positive", type_="check")
        batch.drop_constraint("ck_action_execution_invoice_positive", type_="check")
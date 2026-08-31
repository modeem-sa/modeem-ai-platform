"""Harden operation histories as append-only evidence.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _install_append_only_trigger(table: str) -> None:
    function = f"block_{table}_mutation"
    trigger = f"trg_{table}_append_only"
    op.execute(
        f"""
        CREATE FUNCTION {function}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '{table} is append-only';
        END;
        $$;
        CREATE TRIGGER {trigger}
        BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION {function}();
        """
    )


def _drop_append_only_trigger(table: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute(f"DROP FUNCTION IF EXISTS block_{table}_mutation()")


def upgrade() -> None:
    op.create_table(
        "operation_action_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "action_id",
            sa.Uuid(),
            sa.ForeignKey("operation_actions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("operation_tasks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("proposal_hash", sa.String(64), nullable=False),
        sa.Column("detail", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_operation_action_history_version"),
        sa.CheckConstraint(
            "actor_type IN ('user', 'worker', 'system')",
            name="ck_operation_action_history_actor_type",
        ),
        sa.CheckConstraint(
            "event IN ('generated', 'regenerated', 'submitted', 'rejected', "
            "'approved', 'retry_queued', 'executing', 'succeeded', 'failed')",
            name="ck_operation_action_history_event",
        ),
    )
    op.create_index(
        "ix_operation_action_history_action_id", "operation_action_history", ["action_id"]
    )
    op.create_index(
        "ix_operation_action_history_task_id", "operation_action_history", ["task_id"]
    )
    op.create_index(
        "ix_operation_action_history_tenant_id", "operation_action_history", ["tenant_id"]
    )
    _install_append_only_trigger("operation_action_history")


def downgrade() -> None:
    _drop_append_only_trigger("operation_action_history")
    op.drop_index(
        "ix_operation_action_history_tenant_id", table_name="operation_action_history"
    )
    op.drop_index(
        "ix_operation_action_history_task_id", table_name="operation_action_history"
    )
    op.drop_index(
        "ix_operation_action_history_action_id", table_name="operation_action_history"
    )
    op.drop_table("operation_action_history")

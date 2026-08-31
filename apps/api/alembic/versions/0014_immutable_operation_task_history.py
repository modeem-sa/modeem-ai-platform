"""Allow parent cascades while keeping operation task history append-only.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _install_cascade_aware_protection() -> None:
    op.execute(
        """
        CREATE FUNCTION protect_operation_task_history()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'operation_task_history is append-only'
                    USING ERRCODE = '55000';
            END IF;

            -- A direct DELETE starts at trigger depth 1. The intended
            -- operation_tasks -> history ON DELETE CASCADE reaches this
            -- trigger at a greater depth and remains allowed.
            IF TG_OP = 'DELETE' AND pg_trigger_depth() <= 1 THEN
                RAISE EXCEPTION 'operation_task_history is append-only'
                    USING ERRCODE = '55000';
            END IF;

            RETURN OLD;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER operation_task_history_append_only
        BEFORE UPDATE OR DELETE ON operation_task_history
        FOR EACH ROW
        EXECUTE FUNCTION protect_operation_task_history();
        """
    )


def _install_strict_protection() -> None:
    op.execute(
        """
        CREATE FUNCTION block_operation_task_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'operation_task_history is append-only';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_operation_task_history_append_only
        BEFORE UPDATE OR DELETE ON operation_task_history
        FOR EACH ROW
        EXECUTE FUNCTION block_operation_task_history_mutation();
        """
    )


def upgrade() -> None:
    op.drop_constraint(
        "operation_task_history_task_id_fkey",
        "operation_task_history",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "operation_task_history_task_id_fkey",
        "operation_task_history",
        "operation_tasks",
        ["task_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute(
        "DROP TRIGGER IF EXISTS trg_operation_task_history_append_only "
        "ON operation_task_history"
    )
    op.execute("DROP FUNCTION IF EXISTS block_operation_task_history_mutation()")
    _install_cascade_aware_protection()


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS operation_task_history_append_only "
        "ON operation_task_history"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_operation_task_history()")
    _install_strict_protection()

    op.drop_constraint(
        "operation_task_history_task_id_fkey",
        "operation_task_history",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "operation_task_history_task_id_fkey",
        "operation_task_history",
        "operation_tasks",
        ["task_id"],
        ["id"],
        ondelete="RESTRICT",
    )
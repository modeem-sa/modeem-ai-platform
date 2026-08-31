"""Add Odoo task provenance and durable action proposals.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ensure_operation_schema() -> None:
    path = Path(__file__).with_name("0007_operation_tasks.py")
    spec = spec_from_file_location("_modeem_operation_tasks_0007", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("operation tasks migration could not be loaded")
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.upgrade()


def upgrade() -> None:
    # Some deployed databases used revision 0007 for the plural board schema.
    # Ensure the singular execution schema exists before adding source fields.
    _ensure_operation_schema()
    op.add_column("connections", sa.Column("odoo_company_id", sa.Integer(), nullable=True))
    for name, typ in (("source_type", sa.String(32)), ("source_connection_id", sa.Uuid()),
                      ("source_record_id", sa.Integer()), ("source_signal", sa.String(64)),
                      ("source_reference", sa.String(255)), ("source_snapshot_json", sa.Text()),
                      ("source_synced_at", sa.DateTime(timezone=True)), ("source_sync_state", sa.String(32))):
        op.add_column("operation_tasks", sa.Column(name, typ, nullable=True))
    op.create_foreign_key("fk_operation_tasks_source_connection", "operation_tasks", "connections", ["source_connection_id"], ["id"], ondelete="SET NULL")
    op.create_unique_constraint("uq_operation_tasks_odoo_signal", "operation_tasks", ["tenant_id", "source_connection_id", "source_record_id", "source_signal"])
    op.create_table("operation_actions",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("operation_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("proposal_json", sa.Text(), nullable=False), sa.Column("proposal_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("approved_hash", sa.String(64)), sa.Column("approved_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)), sa.Column("idempotency_marker", sa.String(64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("error", sa.Text()),
        sa.Column("external_activity_id", sa.Integer()), sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_operation_actions_task"), sa.UniqueConstraint("idempotency_marker"),
        sa.CheckConstraint("status IN ('proposed', 'awaiting_approval', 'approved', 'queued', 'executing', 'verifying', 'succeeded', 'failed')", name="ck_operation_actions_status"))
    op.create_index("ix_operation_actions_tenant_id", "operation_actions", ["tenant_id"])
    op.create_table("recurring_task_templates", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False), sa.Column("title", sa.String(255), nullable=False), sa.Column("description", sa.Text()), sa.Column("category", sa.String(32), nullable=False), sa.Column("priority", sa.String(16), nullable=False), sa.Column("frequency", sa.String(16), nullable=False), sa.Column("timezone", sa.String(64), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_recurring_task_templates_tenant_id", "recurring_task_templates", ["tenant_id"])
    op.create_table("recurring_task_occurrences", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("template_id", sa.Uuid(), sa.ForeignKey("recurring_task_templates.id", ondelete="CASCADE"), nullable=False), sa.Column("task_id", sa.Uuid(), sa.ForeignKey("operation_tasks.id", ondelete="CASCADE"), nullable=False), sa.Column("occurrence_date", sa.String(10), nullable=False), sa.UniqueConstraint("template_id", "occurrence_date", name="uq_recurring_task_occurrence"))
def downgrade() -> None:
    op.drop_column("connections", "odoo_company_id")
    op.drop_table("recurring_task_occurrences"); op.drop_index("ix_recurring_task_templates_tenant_id", table_name="recurring_task_templates"); op.drop_table("recurring_task_templates")
    op.drop_index("ix_operation_actions_tenant_id", table_name="operation_actions"); op.drop_table("operation_actions")
    op.drop_constraint("uq_operation_tasks_odoo_signal", "operation_tasks", type_="unique")
    op.drop_constraint("fk_operation_tasks_source_connection", "operation_tasks", type_="foreignkey")
    for name in ("source_sync_state", "source_synced_at", "source_snapshot_json", "source_reference", "source_signal", "source_record_id", "source_connection_id", "source_type"): op.drop_column("operation_tasks", name)
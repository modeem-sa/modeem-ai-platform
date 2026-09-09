"""Customer shared-service request foundation.

Revision ID: 0021
Revises: 0020
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _install_append_only_trigger(table: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION prevent_{table}_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '{table} is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_{table}_append_only
        BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION prevent_{table}_mutation()
        """
    )


def _drop_append_only_trigger(table: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute(f"DROP FUNCTION IF EXISTS prevent_{table}_mutation()")


def upgrade() -> None:
    op.drop_constraint("ck_tenant_memberships_role", "tenant_memberships", type_="check")
    op.create_check_constraint("ck_tenant_memberships_role", "tenant_memberships", "role IN ('owner','admin','manager','member','viewer','customer')")
    op.create_table(
        "service_requests",
        sa.Column("id",sa.Uuid(),primary_key=True),
        sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.id",ondelete="CASCADE"),nullable=False),
        sa.Column("requester_id",sa.Uuid(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("assigned_employee_id",sa.Uuid(),sa.ForeignKey("users.id",ondelete="SET NULL")),
        sa.Column("subject",sa.String(255),nullable=False),
        sa.Column("description",sa.Text(),nullable=False),
        sa.Column("requested_module",sa.String(255)),
        sa.Column("priority",sa.String(16),nullable=False),
        sa.Column("source",sa.String(16),nullable=False),
        sa.Column("status",sa.String(32),nullable=False),
        sa.Column("installed_modules_json",sa.Text()),
        sa.Column("workflow_key",sa.String(128)),
        sa.Column("workflow_config_version",sa.Integer()),
        sa.Column("operation_task_id",sa.Uuid(),sa.ForeignKey("operation_tasks.id",ondelete="RESTRICT"),unique=True),
        sa.Column("automation_status",sa.String(16),nullable=False),
        sa.Column("automation_result_json",sa.Text()),
        sa.Column("automation_receipt",sa.String(255)),
        sa.Column("automation_error",sa.Text()),
        sa.Column("automation_queued_at",sa.DateTime(timezone=True)),
        sa.Column("automation_started_at",sa.DateTime(timezone=True)),
        sa.Column("automation_finished_at",sa.DateTime(timezone=True)),
        sa.Column("public_reference",sa.String(32),nullable=False,unique=True),
        sa.Column("version",sa.Integer(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("priority IN ('low','medium','high','urgent')", name="ck_service_requests_priority"),
        sa.CheckConstraint("source IN ('portal','email')", name="ck_service_requests_source"),
        sa.CheckConstraint("status IN ('open','in_progress','waiting_customer','resolved','closed')", name="ck_service_requests_status"),
        sa.CheckConstraint("automation_status IN ('none','queued','running','succeeded','failed')", name="ck_service_requests_automation_status"),
        sa.CheckConstraint("version >= 1", name="ck_service_requests_version"),
    )
    op.create_index("ix_service_requests_tenant_id", "service_requests", ["tenant_id"])
    op.create_index("ix_service_requests_requester_id", "service_requests", ["requester_id"])
    op.create_index("ix_service_requests_assigned_employee_id", "service_requests", ["assigned_employee_id"])
    op.create_index("ix_service_requests_tenant_status", "service_requests", ["tenant_id", "status"])
    op.create_index("ix_service_requests_tenant_assignee_status", "service_requests", ["tenant_id", "assigned_employee_id", "status"])
    op.create_index("ix_service_requests_tenant_requester", "service_requests", ["tenant_id", "requester_id"])
    for table, cols in (
        ("service_request_messages",[("request_id","service_requests"),("tenant_id","tenants"),("author_id","users")]),
        ("service_request_attachments",[("request_id","service_requests"),("tenant_id","tenants"),("uploaded_by_id","users")]),
        ("service_request_events",[("request_id","service_requests"),("tenant_id","tenants"),("actor_id","users")]),
    ):
        extra = [sa.Column("id",sa.Uuid(),primary_key=True)]
        for name, ref in cols: extra.append(sa.Column(name,sa.Uuid(),sa.ForeignKey(f"{ref}.id",ondelete="RESTRICT"),nullable=name!="actor_id"))
        extra += [sa.Column("created_at",sa.DateTime(timezone=True),nullable=False)]
        if table.endswith("messages"): extra += [sa.Column("body",sa.Text(),nullable=False)]
        elif table.endswith("attachments"): extra += [sa.Column("original_name",sa.String(255),nullable=False),sa.Column("storage_key",sa.String(600),nullable=False,unique=True),sa.Column("content_type",sa.String(100),nullable=False),sa.Column("size",sa.Integer(),nullable=False),sa.Column("sha256",sa.String(64),nullable=False),sa.CheckConstraint("size > 0 AND size <= 10485760",name="ck_service_request_attachments_size"),sa.CheckConstraint("length(sha256) = 64",name="ck_service_request_attachments_sha256")]
        else: extra += [sa.Column("event",sa.String(64),nullable=False),sa.Column("payload_json",sa.Text()),sa.Column("version",sa.Integer(),nullable=False)]
        op.create_table(table,*extra)
        op.create_index(f"ix_{table}_request_id", table, ["request_id"])
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        _install_append_only_trigger(table)
    op.create_index("ix_service_request_attachments_request_created", "service_request_attachments", ["request_id", "created_at"])


def downgrade() -> None:
    for table in ("service_request_events","service_request_attachments","service_request_messages"):
        _drop_append_only_trigger(table)
    for table in ("service_request_events","service_request_attachments","service_request_messages","service_requests"):
        op.drop_table(table)
    op.drop_constraint("ck_tenant_memberships_role", "tenant_memberships", type_="check")
    op.create_check_constraint(
        "ck_tenant_memberships_role",
        "tenant_memberships",
        "role IN ('owner','admin','manager','member','viewer')",
    )
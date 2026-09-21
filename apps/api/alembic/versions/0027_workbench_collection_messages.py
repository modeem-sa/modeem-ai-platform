"""Add request-bound, non-delivery collection message drafts."""

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workbench_collection_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("service_request_id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("partner_id", sa.Integer(), nullable=False),
        sa.Column("partner_name", sa.String(255), nullable=False),
        sa.Column("invoice_ids_json", sa.Text(), nullable=False),
        sa.Column("source_evidence_json", sa.Text(), nullable=False),
        sa.Column("draft_content", sa.Text(), nullable=False),
        sa.Column("draft_hash", sa.String(64), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("idempotency_marker", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_request_id"], ["service_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["action_id"], ["operation_actions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("action_id", "partner_id", name="uq_workbench_collection_message_partner"),
        sa.UniqueConstraint("idempotency_marker", name="uq_workbench_collection_message_marker"),
        sa.CheckConstraint("status IN ('draft','awaiting_approval')",
                           name="ck_workbench_collection_message_status"),
        sa.CheckConstraint("partner_id > 0 AND company_id > 0",
                           name="ck_workbench_collection_message_identity"),
        sa.CheckConstraint(
            "(submitted_by_user_id IS NULL AND submitted_at IS NULL) OR "
            "(submitted_by_user_id IS NOT NULL AND submitted_at IS NOT NULL)",
            name="ck_workbench_collection_message_submission",
        ),
        sa.CheckConstraint("length(draft_content) BETWEEN 1 AND 1000",
                           name="ck_workbench_collection_message_draft_length"),
        sa.CheckConstraint("draft_version >= 1 AND source_version >= 1 AND version >= 1",
                           name="ck_workbench_collection_message_versions"),
        sa.CheckConstraint("length(draft_hash) = 64 AND length(source_hash) = 64",
                           name="ck_workbench_collection_message_hash_lengths"),
    )
    op.create_index(
        "ix_workbench_collection_message_tenant_status",
        "workbench_collection_messages", ["tenant_id", "status"],
    )
    op.create_table(
        "workbench_collection_message_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("service_request_id", sa.Uuid(), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("detail", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["workbench_collection_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["service_request_id"], ["service_requests.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "event IN ('generated','regenerated','policy_checked','policy_blocked','submitted')",
            name="ck_workbench_collection_message_event",
        ),
        sa.CheckConstraint("length(content_hash) = 64",
                           name="ck_workbench_collection_message_event_hash"),
        sa.CheckConstraint("length(source_hash) = 64",
                           name="ck_workbench_collection_message_event_source_hash"),
        sa.CheckConstraint("version >= 1", name="ck_workbench_collection_message_event_version"),
        sa.CheckConstraint("actor_type IN ('user','worker','system')",
                           name="ck_workbench_collection_message_event_actor"),
    )
    op.create_index(
        "ix_workbench_collection_message_events_message",
        "workbench_collection_message_events", ["message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workbench_collection_message_events_message",
                  table_name="workbench_collection_message_events")
    op.drop_table("workbench_collection_message_events")
    op.drop_index("ix_workbench_collection_message_tenant_status",
                  table_name="workbench_collection_messages")
    op.drop_table("workbench_collection_messages")
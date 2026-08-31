"""Add fixed invoice-chatter collection message delivery.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invoice_collection_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("operation_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("draft_content", sa.Text(), nullable=False),
        sa.Column("draft_hash", sa.String(64), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_partner_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("approved_content", sa.Text(), nullable=True),
        sa.Column("approved_hash", sa.String(64), nullable=True),
        sa.Column("approved_draft_version", sa.Integer(), nullable=True),
        sa.Column("approved_source_hash", sa.String(64), nullable=True),
        sa.Column("approved_source_version", sa.Integer(), nullable=True),
        sa.Column("approved_partner_id", sa.Integer(), nullable=True),
        sa.Column("approved_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_marker", sa.String(64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(64), nullable=True),
        sa.Column("external_message_id", sa.Integer(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_invoice_collection_messages_task"),
        sa.UniqueConstraint("idempotency_marker", name="uq_invoice_collection_messages_marker"),
        sa.CheckConstraint(
            "status IN ('draft', 'awaiting_approval', 'queued', 'sending', "
            "'verifying', 'succeeded', 'failed')",
            name="ck_invoice_collection_messages_status",
        ),
        sa.CheckConstraint("draft_version >= 1", name="ck_invoice_collection_messages_draft_version"),
        sa.CheckConstraint("source_version >= 1", name="ck_invoice_collection_messages_source_version"),
        sa.CheckConstraint("version >= 1", name="ck_invoice_collection_messages_version"),
        sa.CheckConstraint("attempt_count >= 0 AND attempt_count <= 3", name="ck_invoice_collection_messages_attempts"),
        sa.CheckConstraint("length(draft_content) BETWEEN 1 AND 1000",
                           name="ck_invoice_collection_messages_draft_length"),
        sa.CheckConstraint(
            "length(draft_hash) = 64 AND length(source_hash) = 64 AND "
            "(approved_hash IS NULL OR length(approved_hash) = 64) AND "
            "(approved_source_hash IS NULL OR length(approved_source_hash) = 64)",
            name="ck_invoice_collection_messages_hash_lengths",
        ),
        sa.CheckConstraint("approved_draft_version IS NULL OR approved_draft_version >= 1",
                           name="ck_invoice_collection_messages_approved_version"),
        sa.CheckConstraint("approved_source_version IS NULL OR approved_source_version >= 1",
                           name="ck_invoice_collection_messages_approved_source_version"),
        sa.CheckConstraint("external_message_id IS NULL OR external_message_id > 0",
                           name="ck_invoice_collection_messages_receipt"),
        sa.CheckConstraint(
            "source_partner_id > 0 AND (approved_partner_id IS NULL OR approved_partner_id > 0)",
            name="ck_invoice_collection_messages_partner_ids",
        ),
        sa.CheckConstraint(
            "(approved_content IS NULL AND approved_hash IS NULL AND approved_draft_version IS NULL "
            "AND approved_source_hash IS NULL AND approved_source_version IS NULL "
            "AND approved_partner_id IS NULL AND approved_by_user_id IS NULL AND approved_at IS NULL) OR "
            "(approved_content IS NOT NULL AND approved_hash IS NOT NULL "
            "AND approved_draft_version IS NOT NULL AND approved_source_hash IS NOT NULL "
            "AND approved_source_version IS NOT NULL AND approved_partner_id IS NOT NULL "
            "AND approved_by_user_id IS NOT NULL "
            "AND approved_at IS NOT NULL)",
            name="ck_invoice_collection_messages_approval_complete",
        ),
    )
    op.create_index("ix_invoice_collection_messages_tenant_status",
                    "invoice_collection_messages", ["tenant_id", "status"])

    op.create_table(
        "invoice_collection_message_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("invoice_collection_messages.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("operation_tasks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("detail", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_invoice_collection_message_events_version"),
        sa.CheckConstraint("length(content_hash) = 64",
                           name="ck_invoice_collection_message_events_hash_length"),
        sa.CheckConstraint("actor_type IN ('user', 'worker', 'system')",
                           name="ck_invoice_collection_message_events_actor_type"),
        sa.CheckConstraint(
            "event IN ('generated', 'regenerated', 'submitted', 'rejected', "
            "'approved', 'retry_queued', 'sending', 'sent', 'verifying', 'verified', "
            "'succeeded', 'failed')",
            name="ck_invoice_collection_message_events_event",
        ),
    )
    op.create_index("ix_invoice_collection_message_events_message_id",
                    "invoice_collection_message_events", ["message_id"])
    op.create_index("ix_invoice_collection_message_events_tenant_id",
                    "invoice_collection_message_events", ["tenant_id"])

    op.execute(
        """
        CREATE FUNCTION block_invoice_collection_message_event_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'invoice_collection_message_events is append-only';
        END;
        $$;
        CREATE TRIGGER trg_invoice_collection_message_events_append_only
        BEFORE UPDATE OR DELETE ON invoice_collection_message_events
        FOR EACH ROW EXECUTE FUNCTION block_invoice_collection_message_event_mutation();

        CREATE FUNCTION block_approved_collection_message_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.approved_content IS NOT NULL AND (
                NEW.approved_content IS DISTINCT FROM OLD.approved_content OR
                NEW.approved_hash IS DISTINCT FROM OLD.approved_hash OR
                NEW.approved_draft_version IS DISTINCT FROM OLD.approved_draft_version OR
                NEW.approved_source_hash IS DISTINCT FROM OLD.approved_source_hash OR
                NEW.approved_source_version IS DISTINCT FROM OLD.approved_source_version OR
                NEW.approved_partner_id IS DISTINCT FROM OLD.approved_partner_id OR
                NEW.approved_by_user_id IS DISTINCT FROM OLD.approved_by_user_id OR
                NEW.approved_at IS DISTINCT FROM OLD.approved_at
            ) THEN
                RAISE EXCEPTION 'approved collection message is immutable';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER trg_approved_collection_message_immutable
        BEFORE UPDATE ON invoice_collection_messages
        FOR EACH ROW EXECUTE FUNCTION block_approved_collection_message_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_approved_collection_message_immutable ON invoice_collection_messages")
    op.execute("DROP FUNCTION IF EXISTS block_approved_collection_message_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_invoice_collection_message_events_append_only ON invoice_collection_message_events")
    op.execute("DROP FUNCTION IF EXISTS block_invoice_collection_message_event_mutation()")
    op.drop_index("ix_invoice_collection_message_events_tenant_id",
                  table_name="invoice_collection_message_events")
    op.drop_index("ix_invoice_collection_message_events_message_id",
                  table_name="invoice_collection_message_events")
    op.drop_table("invoice_collection_message_events")
    op.drop_index("ix_invoice_collection_messages_tenant_status",
                  table_name="invoice_collection_messages")
    op.drop_table("invoice_collection_messages")
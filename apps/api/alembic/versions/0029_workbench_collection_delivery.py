"""Add the controlled Phase 4D-B Workbench delivery lifecycle."""

import sqlalchemy as sa

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("queued_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivery_anchor_invoice_id", sa.Integer(), nullable=True),
        sa.Column("external_message_id", sa.Integer(), nullable=True),
        sa.Column("delivery_error_code", sa.String(64), nullable=True),
        sa.Column("delivery_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(64), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("workbench_collection_messages", column)
    op.create_foreign_key(
        "fk_workbench_collection_message_queued_user",
        "workbench_collection_messages", "users",
        ["queued_by_user_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_workbench_collection_message_claim_token",
        "workbench_collection_messages", ["claim_token"],
    )
    op.create_check_constraint(
        "ck_workbench_collection_message_anchor", "workbench_collection_messages",
        "delivery_anchor_invoice_id IS NULL OR delivery_anchor_invoice_id > 0",
    )
    op.drop_constraint("ck_workbench_collection_message_status", "workbench_collection_messages", type_="check")
    op.create_check_constraint(
        "ck_workbench_collection_message_status", "workbench_collection_messages",
        "status IN ('draft','awaiting_approval','approved','queued','sending','verifying','succeeded','failed')",
    )
    op.create_check_constraint(
        "ck_workbench_collection_message_attempts", "workbench_collection_messages",
        "attempt_count >= 0 AND attempt_count <= 3",
    )
    op.drop_constraint("ck_workbench_collection_message_approval_complete", "workbench_collection_messages", type_="check")
    op.create_check_constraint(
        "ck_workbench_collection_message_approval_complete", "workbench_collection_messages",
        "(status IN ('approved','queued','sending','verifying','succeeded','failed') AND approved_content IS NOT NULL "
        "AND approved_hash IS NOT NULL AND approved_draft_version IS NOT NULL AND approved_source_hash IS NOT NULL "
        "AND approved_source_version IS NOT NULL AND approved_partner_id IS NOT NULL AND approved_by_user_id IS NOT NULL "
        "AND approved_at IS NOT NULL) OR "
        "(status IN ('draft','awaiting_approval') AND approved_content IS NULL AND approved_hash IS NULL "
        "AND approved_draft_version IS NULL AND approved_source_hash IS NULL AND approved_source_version IS NULL "
        "AND approved_partner_id IS NULL AND approved_by_user_id IS NULL AND approved_at IS NULL)",
    )
    op.drop_constraint("ck_workbench_collection_message_event", "workbench_collection_message_events", type_="check")
    op.create_check_constraint(
        "ck_workbench_collection_message_event", "workbench_collection_message_events",
        "event IN ('generated','regenerated','policy_checked','policy_blocked','submitted','approved','rejected',"
        "'queued','sending','verifying','sent','verified','succeeded','failed','retry_queued')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_workbench_collection_message_event", "workbench_collection_message_events", type_="check")
    op.create_check_constraint(
        "ck_workbench_collection_message_event", "workbench_collection_message_events",
        "event IN ('generated','regenerated','policy_checked','policy_blocked','submitted','approved','rejected')",
    )
    op.drop_constraint("ck_workbench_collection_message_approval_complete", "workbench_collection_messages", type_="check")
    op.create_check_constraint(
        "ck_workbench_collection_message_approval_complete", "workbench_collection_messages",
        "(status = 'approved' AND approved_content IS NOT NULL AND approved_hash IS NOT NULL "
        "AND approved_draft_version IS NOT NULL AND approved_source_hash IS NOT NULL "
        "AND approved_source_version IS NOT NULL AND approved_partner_id IS NOT NULL "
        "AND approved_by_user_id IS NOT NULL AND approved_at IS NOT NULL) OR "
        "(status <> 'approved' AND approved_content IS NULL AND approved_hash IS NULL "
        "AND approved_draft_version IS NULL AND approved_source_hash IS NULL "
        "AND approved_source_version IS NULL AND approved_partner_id IS NULL "
        "AND approved_by_user_id IS NULL AND approved_at IS NULL)",
    )
    op.drop_constraint("ck_workbench_collection_message_status", "workbench_collection_messages", type_="check")
    op.drop_constraint("ck_workbench_collection_message_attempts", "workbench_collection_messages", type_="check")
    op.create_check_constraint(
        "ck_workbench_collection_message_status", "workbench_collection_messages",
        "status IN ('draft','awaiting_approval','approved')",
    )
    op.drop_constraint("fk_workbench_collection_message_queued_user", "workbench_collection_messages", type_="foreignkey")
    op.drop_constraint("uq_workbench_collection_message_claim_token", "workbench_collection_messages", type_="unique")
    op.drop_constraint("ck_workbench_collection_message_anchor", "workbench_collection_messages", type_="check")
    for name in (
        "lease_expires_at", "claimed_at", "last_delivery_at", "verified_at",
        "delivery_started_at", "delivery_error_code", "external_message_id",
        "delivery_anchor_invoice_id", "attempt_count", "queued_at", "queued_by_user_id",
        "next_attempt_at", "claim_token",
    ):
        op.drop_column("workbench_collection_messages", name)
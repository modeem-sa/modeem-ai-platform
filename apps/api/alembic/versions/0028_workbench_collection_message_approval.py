"""Add the Phase 4D-A human approval boundary."""

import sqlalchemy as sa

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workbench_collection_messages",
        sa.Column("draft_author_user_id", sa.Uuid(), nullable=True),
    )
    op.execute(
        "UPDATE workbench_collection_messages "
        "SET draft_author_user_id = created_by_user_id "
        "WHERE draft_author_user_id IS NULL"
    )
    op.alter_column(
        "workbench_collection_messages",
        "draft_author_user_id",
        nullable=False,
    )
    op.create_foreign_key(
        "fk_workbench_collection_message_draft_author",
        "workbench_collection_messages",
        "users",
        ["draft_author_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "workbench_collection_messages",
        sa.Column("approved_content", sa.Text(), nullable=True),
    )
    op.add_column(
        "workbench_collection_messages",
        sa.Column("approved_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "workbench_collection_messages",
        sa.Column("approved_draft_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "workbench_collection_messages",
        sa.Column("approved_source_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "workbench_collection_messages",
        sa.Column("approved_source_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "workbench_collection_messages",
        sa.Column("approved_partner_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "workbench_collection_messages",
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "workbench_collection_messages",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "workbench_collection_messages",
        sa.Column("rejected_by_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "workbench_collection_messages",
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "workbench_collection_messages",
        sa.Column("rejection_reason", sa.String(500), nullable=True),
    )
    op.create_foreign_key(
        "fk_workbench_collection_message_approved_user",
        "workbench_collection_messages",
        "users",
        ["approved_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_workbench_collection_message_rejected_user",
        "workbench_collection_messages",
        "users",
        ["rejected_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "ck_workbench_collection_message_status",
        "workbench_collection_messages",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workbench_collection_message_status",
        "workbench_collection_messages",
        "status IN ('draft','awaiting_approval','approved')",
    )
    op.create_check_constraint(
        "ck_workbench_collection_message_approval_complete",
        "workbench_collection_messages",
        "(status = 'approved' AND approved_content IS NOT NULL "
        "AND approved_hash IS NOT NULL AND approved_draft_version IS NOT NULL "
        "AND approved_source_hash IS NOT NULL AND approved_source_version IS NOT NULL "
        "AND approved_partner_id IS NOT NULL AND approved_by_user_id IS NOT NULL "
        "AND approved_at IS NOT NULL) OR "
        "(status <> 'approved' AND approved_content IS NULL AND approved_hash IS NULL "
        "AND approved_draft_version IS NULL AND approved_source_hash IS NULL "
        "AND approved_source_version IS NULL AND approved_partner_id IS NULL "
        "AND approved_by_user_id IS NULL AND approved_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_workbench_collection_message_rejection",
        "workbench_collection_messages",
        "(rejected_by_user_id IS NULL AND rejected_at IS NULL) OR "
        "(rejected_by_user_id IS NOT NULL AND rejected_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_workbench_collection_message_approval_values",
        "workbench_collection_messages",
        "(approved_hash IS NULL OR length(approved_hash) = 64) AND "
        "(approved_source_hash IS NULL OR length(approved_source_hash) = 64) AND "
        "(approved_content IS NULL OR length(approved_content) BETWEEN 1 AND 1000) AND "
        "(approved_draft_version IS NULL OR approved_draft_version >= 1) AND "
        "(approved_source_version IS NULL OR approved_source_version >= 1) AND "
        "(approved_partner_id IS NULL OR approved_partner_id > 0)",
    )
    op.create_check_constraint(
        "ck_workbench_collection_message_draft_author",
        "workbench_collection_messages",
        "draft_author_user_id IS NOT NULL",
    )
    op.drop_constraint(
        "ck_workbench_collection_message_event",
        "workbench_collection_message_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workbench_collection_message_event",
        "workbench_collection_message_events",
        "event IN ('generated','regenerated','policy_checked','policy_blocked',"
        "'submitted','approved','rejected')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_workbench_collection_message_event",
        "workbench_collection_message_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workbench_collection_message_event",
        "workbench_collection_message_events",
        "event IN ('generated','regenerated','policy_checked','policy_blocked','submitted')",
    )
    op.drop_constraint(
        "ck_workbench_collection_message_rejection",
        "workbench_collection_messages",
        type_="check",
    )
    op.drop_constraint(
        "ck_workbench_collection_message_approval_complete",
        "workbench_collection_messages",
        type_="check",
    )
    op.drop_constraint(
        "ck_workbench_collection_message_approval_values",
        "workbench_collection_messages",
        type_="check",
    )
    op.drop_constraint(
        "ck_workbench_collection_message_draft_author",
        "workbench_collection_messages",
        type_="check",
    )
    op.drop_constraint(
        "ck_workbench_collection_message_status",
        "workbench_collection_messages",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workbench_collection_message_status",
        "workbench_collection_messages",
        "status IN ('draft','awaiting_approval')",
    )
    op.drop_constraint(
        "fk_workbench_collection_message_rejected_user",
        "workbench_collection_messages",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_workbench_collection_message_approved_user",
        "workbench_collection_messages",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_workbench_collection_message_draft_author",
        "workbench_collection_messages",
        type_="foreignkey",
    )
    for name in (
        "rejection_reason",
        "rejected_at",
        "rejected_by_user_id",
        "approved_at",
        "approved_by_user_id",
        "approved_partner_id",
        "approved_source_version",
        "approved_source_hash",
        "approved_draft_version",
        "approved_hash",
        "approved_content",
        "draft_author_user_id",
    ):
        op.drop_column("workbench_collection_messages", name)
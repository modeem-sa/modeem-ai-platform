"""Record collection communication-policy checks in the append-only event log.

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_invoice_collection_message_events_event",
        "invoice_collection_message_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_invoice_collection_message_events_event",
        "invoice_collection_message_events",
        "event IN ('generated', 'regenerated', 'submitted', 'rejected', "
        "'approved', 'policy_checked', 'policy_blocked', 'retry_queued', 'sending', "
        "'sent', 'verifying', 'verified', 'succeeded', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_invoice_collection_message_events_event",
        "invoice_collection_message_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_invoice_collection_message_events_event",
        "invoice_collection_message_events",
        "event IN ('generated', 'regenerated', 'submitted', 'rejected', "
        "'approved', 'retry_queued', 'sending', 'sent', 'verifying', 'verified', "
        "'succeeded', 'failed')",
    )
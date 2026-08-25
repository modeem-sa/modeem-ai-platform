"""Odoo connectivity metadata for connections (Phase 2C).

Adds auth_mode and safe detected metadata fields. No secrets are stored in
any of these columns. Migrations 0001-0004 are untouched.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "connections",
        sa.Column("auth_mode", sa.String(16), nullable=False, server_default="auto"),
    )
    op.add_column(
        "connections", sa.Column("detected_odoo_version", sa.String(64), nullable=True)
    )
    op.add_column(
        "connections", sa.Column("detected_odoo_major", sa.Integer(), nullable=True)
    )
    op.add_column(
        "connections", sa.Column("detected_edition", sa.String(16), nullable=True)
    )
    op.add_column(
        "connections", sa.Column("selected_transport", sa.String(16), nullable=True)
    )
    op.add_column("connections", sa.Column("capabilities_json", sa.Text(), nullable=True))
    op.add_column(
        "connections", sa.Column("last_test_error_code", sa.String(64), nullable=True)
    )
    op.create_check_constraint(
        "ck_connections_auth_mode",
        "connections",
        "auth_mode IN ('auto', 'password', 'api_key')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_connections_auth_mode", "connections", type_="check")
    for col in (
        "last_test_error_code",
        "capabilities_json",
        "selected_transport",
        "detected_edition",
        "detected_odoo_major",
        "detected_odoo_version",
        "auth_mode",
    ):
        op.drop_column("connections", col)

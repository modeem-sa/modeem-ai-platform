"""Add optional, Modeem-controlled Odoo module scopes to memberships.

Revision ID: 0019
Revises: 0018
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_memberships",
        sa.Column("odoo_module_scope_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_memberships", "odoo_module_scope_json")
"""Role CHECK constraint on tenant_memberships

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-08

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_CHECK_SQL = "role IN ('owner', 'admin', 'manager', 'member', 'viewer')"


def upgrade() -> None:
    op.create_check_constraint(
        "ck_tenant_memberships_role",
        "tenant_memberships",
        ROLE_CHECK_SQL,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tenant_memberships_role", "tenant_memberships", type_="check"
    )

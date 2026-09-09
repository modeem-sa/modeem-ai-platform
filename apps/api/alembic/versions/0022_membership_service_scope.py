"""Add optional server-owned service scopes to tenant memberships."""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_memberships", sa.Column("service_scope_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant_memberships", "service_scope_json")
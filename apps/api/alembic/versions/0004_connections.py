"""Tenant-scoped connections with encrypted credentials

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-08

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("database_name", sa.String(length=200), nullable=True),
        sa.Column("username", sa.String(length=200), nullable=True),
        sa.Column("encrypted_credentials", sa.LargeBinary(), nullable=True),
        sa.Column("encryption_version", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="configured"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(length=64), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_connections_tenant_name"),
        sa.CheckConstraint("provider IN ('odoo')", name="ck_connections_provider"),
        sa.CheckConstraint(
            "status IN ('configured', 'disabled')", name="ck_connections_status"
        ),
    )
    op.create_index("ix_connections_tenant_id", "connections", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_connections_tenant_id", table_name="connections")
    op.drop_table("connections")

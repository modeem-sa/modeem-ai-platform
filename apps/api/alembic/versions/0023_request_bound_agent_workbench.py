"""Add persistent request-bound AI workbench sessions and messages."""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("service_request_id", sa.Uuid(), nullable=False),
        sa.Column("employee_user_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider_model", sa.String(length=200), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=True),
        sa.Column("latest_analysis_json", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_request_id"], ["service_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('active','completed','failed')", name="ck_agent_sessions_status"),
        sa.UniqueConstraint(
            "tenant_id",
            "service_request_id",
            "employee_user_id",
            name="uq_agent_sessions_tenant_request_employee",
        ),
    )
    op.create_index(
        "ix_agent_sessions_tenant_request", "agent_sessions", ["tenant_id", "service_request_id"]
    )
    op.create_index(
        "ix_agent_sessions_employee_status", "agent_sessions", ["employee_user_id", "status"]
    )
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("analysis_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.CheckConstraint("role IN ('user','assistant','system')", name="ck_agent_messages_role"),
    )
    op.create_index(
        "ix_agent_messages_session_created", "agent_messages", ["session_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_messages_session_created", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_index("ix_agent_sessions_employee_status", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_tenant_request", table_name="agent_sessions")
    op.drop_table("agent_sessions")
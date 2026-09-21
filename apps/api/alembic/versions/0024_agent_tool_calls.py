"""Add durable request-bound read-only Agent tool execution records."""

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("service_request_id", sa.Uuid(), nullable=False),
        sa.Column("employee_user_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=True),
        sa.Column("tool_key", sa.String(length=128), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("safe_input_json", sa.Text(), nullable=False),
        sa.Column("safe_result_summary_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["service_request_id"], ["service_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["employee_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('started','completed','failed')",
            name="ck_agent_tool_calls_status",
        ),
        sa.CheckConstraint("mode = 'read'", name="ck_agent_tool_calls_read_only"),
    )
    op.create_index(
        "ix_agent_tool_calls_session_started",
        "agent_tool_calls",
        ["session_id", "started_at"],
    )
    op.create_index(
        "ix_agent_tool_calls_tenant_request",
        "agent_tool_calls",
        ["tenant_id", "service_request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_tool_calls_tenant_request", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_session_started", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")
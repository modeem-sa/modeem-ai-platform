"""Request and response schemas for operations tasks."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TaskCategory = Literal["administrative", "financial", "human_resources"]
TaskPriority = Literal["low", "medium", "high", "urgent"]
TaskStatus = Literal[
    "pending", "in_progress", "completed", "submitted_for_approval", "approved", "rejected"
]


class OperationTaskCreate(BaseModel):
    tenant_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    category: TaskCategory
    procedure_type: str | None = Field(default=None, min_length=1, max_length=64)
    request_data: dict[str, str] | None = None
    priority: TaskPriority
    due_at: datetime | None = None
    assigned_user_id: uuid.UUID | None = None

    @field_validator("request_data")
    @classmethod
    def validate_request_data(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        if len(value) > 12:
            raise ValueError("Request data cannot contain more than 12 fields")
        for key, item in value.items():
            if not key or len(key) > 64 or len(item) > 1000:
                raise ValueError("Request data contains an invalid field")
        return value


class HrReviewTaskCreate(BaseModel):
    # UUIDs and dates arrive as JSON strings; field bounds still reject
    # malformed identifiers and non-positive numeric references.
    model_config = ConfigDict(extra="forbid")

    tenant_id: uuid.UUID
    connection_id: uuid.UUID
    resource: Literal[
        "employees_summary",
        "attendance_summary",
        "leaves_summary",
        "payroll_summary",
    ]
    record_id: int = Field(ge=1)
    employee_id: int | None = Field(default=None, ge=1)
    date_from: date | None = None
    date_to: date | None = None
    priority: TaskPriority = "medium"
    assigned_user_id: uuid.UUID | None = None


class OperationTaskAction(BaseModel):
    expected_version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)


class OperationActionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    expected_action_version: int | None = Field(default=None, ge=1)
    expected_proposal_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class OperationActionExactRequest(BaseModel):
    expected_version: int = Field(ge=1)
    expected_action_version: int = Field(ge=1)
    expected_proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class OperationActionOut(BaseModel):
    id: uuid.UUID
    status: str
    version: int
    proposal: dict
    proposal_hash: str
    approved_hash: str | None
    approved_by_user_id: uuid.UUID | None
    approved_at: datetime | None
    attempt_count: int
    error: str | None
    external_activity_id: int | None
    verified_at: datetime | None
    workflow_key: str | None
    workflow_config_version: int | None


class CollectionMessageGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(ge=1)


class CollectionMessageExactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(ge=1)
    expected_message_version: int = Field(ge=1)
    expected_draft_version: int = Field(ge=1)
    expected_draft_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_source_version: int = Field(ge=1)
    expected_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CollectionMessageOut(BaseModel):
    id: uuid.UUID
    channel: Literal["odoo_customer_invoice_chatter"]
    status: str
    version: int
    draft_content: str
    draft_version: int
    draft_hash: str
    source_hash: str
    source_version: int
    approved_content: str | None
    approved_draft_version: int | None
    approved_hash: str | None
    approved_source_hash: str | None
    approved_source_version: int | None
    approved_by_user_id: uuid.UUID | None
    approved_at: datetime | None
    attempt_count: int
    delivery_error: str | None
    receipt_message_id: int | None
    verified_at: datetime | None


class OperationTaskOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str
    title: str
    description: str | None
    category: TaskCategory
    procedure_type: str | None
    request_data: dict[str, str] | None
    priority: TaskPriority
    status: TaskStatus
    assigned_user_id: uuid.UUID | None
    assignee_name: str | None
    created_by_user_id: uuid.UUID
    version: int
    due_at: datetime | None
    completed_at: datetime | None
    submitted_at: datetime | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime
    updated_at: datetime
    available_actions: list[str]
    source_type: str
    source_connection_id: uuid.UUID | None
    source_record_id: int | None
    source_signal: str | None
    source_reference: str | None
    source_snapshot: dict | None
    source_sync_state: str | None
    source_synced_at: datetime | None
    action: OperationActionOut | None = None
    collection_message: CollectionMessageOut | None = None


class OperationTaskListOut(BaseModel):
    items: list[OperationTaskOut]
    total: int
    summary: dict[str, int]


class OperationMemberOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    role: str


class OperationTenantBootstrapOut(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    can_create: bool
    members: list[OperationMemberOut]


class OperationBootstrapOut(BaseModel):
    tenants: list[OperationTenantBootstrapOut]

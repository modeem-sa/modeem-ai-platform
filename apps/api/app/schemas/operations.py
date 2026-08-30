"""Request and response schemas for operations tasks."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TaskCategory = Literal["administrative", "financial"]
TaskPriority = Literal["low", "medium", "high", "urgent"]
TaskStatus = Literal[
    "pending", "in_progress", "completed", "submitted_for_approval", "approved", "rejected"
]


class OperationTaskCreate(BaseModel):
    tenant_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    category: TaskCategory
    priority: TaskPriority
    due_at: datetime | None = None
    assigned_user_id: uuid.UUID | None = None


class OperationTaskAction(BaseModel):
    expected_version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)


class OperationTaskOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str
    title: str
    description: str | None
    category: TaskCategory
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
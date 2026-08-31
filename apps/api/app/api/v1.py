"""API v1 routes — public health/info + internal-auth dashboard data.

The auth and connections routers are included directly by app.main (they
declare their own /api/v1 prefixes); they are NOT re-included here.

Dashboard endpoints are called by the Next.js server-side proxy, which
adds X-Internal-Token (verified against SESSION_SECRET) and X-Tenant-ID.
The duplicate GET /connections listing was removed: connection management
is served by app.api.connections (cookie-auth, tenant-scoped).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.csrf import require_csrf
from app.api.deps import get_current_user, get_db, get_tenant_id, require_internal_auth
from app.core.config import get_settings
from app.models import (
    AuditLog,
    Connection,
    Execution,
    OperationsTask,
    Tenant,
    TenantMembership,
    User,
    Workflow,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1")

DbDep = Annotated[Session, Depends(get_db)]
AuthDep = Annotated[None, Depends(require_internal_auth)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]
UserDep = Annotated[User, Depends(get_current_user)]


# ── Public endpoints ────────────────────────────────────────────────────────


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "healthy", "service": settings.service_name}


@router.get("/info")
def info() -> dict[str, str]:
    settings = get_settings()
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "api_version": settings.api_version,
    }


# ── Protected data endpoints (internal token + tenant header) ───────────────


class StatsResponse(BaseModel):
    active_workflows: int
    successful_executions: int
    failed_executions: int
    connected_systems: int


class ExecutionItem(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID | None
    status: str
    started_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class WorkflowItem(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AuditLogItem(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    actor_type: str
    actor_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    correlation_id: str | None
    metadata_json: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class OperationsTaskItem(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str
    title: str
    description: str | None
    work_type: Literal["administrative", "financial"]
    status: Literal[
        "upcoming", "overdue", "awaiting_approval", "needs_intervention", "completed"
    ]
    priority: Literal["urgent", "high", "normal"]
    due_at: datetime
    assignee_name: str
    source: str
    version: int
    approval_state: Literal["none", "pending", "approved", "rejected"]
    last_note: str | None
    available_actions: list[
        Literal[
            "complete",
            "submit_for_approval",
            "approve",
            "reject",
            "record_intervention",
        ]
    ]


class OperationsTaskActionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)


class AssociationItem(BaseModel):
    id: uuid.UUID
    name: str
    count: int


class OperationsSummary(BaseModel):
    total_active: int
    urgent: int
    overdue: int
    needs_intervention: int


class OperationsBoardResponse(BaseModel):
    items: list[OperationsTaskItem]
    total: int
    associations: list[AssociationItem]
    summary: OperationsSummary


_BOARD_MANAGER_ROLES = {"owner", "admin", "manager"}
_BOARD_TRANSITIONS = {
    "complete": ({"upcoming", "overdue", "needs_intervention"}, "completed"),
    "submit_for_approval": ({"completed"}, "awaiting_approval"),
    "approve": ({"awaiting_approval"}, "completed"),
    "reject": ({"awaiting_approval"}, "needs_intervention"),
    "record_intervention": ({"upcoming", "overdue"}, "needs_intervention"),
}


def _board_memberships(db: Session, user: User) -> dict[uuid.UUID, str]:
    return dict(
        db.execute(
            select(TenantMembership.tenant_id, TenantMembership.role)
            .join(Tenant, Tenant.id == TenantMembership.tenant_id)
            .where(
                TenantMembership.user_id == user.id,
                TenantMembership.is_active.is_(True),
                Tenant.is_active.is_(True),
            )
        ).all()
    )


def _board_available_actions(task: OperationsTask, role: str) -> list[str]:
    if task.status in {"upcoming", "overdue"}:
        return ["complete", "record_intervention"]
    if task.status == "needs_intervention":
        return ["complete"]
    if task.status == "completed" and task.approval_state != "approved":
        return ["submit_for_approval"]
    if task.status == "awaiting_approval" and role in _BOARD_MANAGER_ROLES:
        return ["approve", "reject"]
    return []


def _board_task_item(
    task: OperationsTask, tenant_name: str, role: str
) -> OperationsTaskItem:
    return OperationsTaskItem(
        id=task.id,
        tenant_id=task.tenant_id,
        tenant_name=tenant_name,
        title=task.title,
        description=task.description,
        work_type=task.work_type,
        status=task.status,
        priority=task.priority,
        due_at=task.due_at,
        assignee_name=task.assignee_name,
        source=task.source,
        version=task.version,
        approval_state=task.approval_state,
        last_note=task.last_note,
        available_actions=_board_available_actions(task, role),
    )


@router.get("/stats", response_model=StatsResponse)
def stats(db: DbDep, _auth: AuthDep, tenant_id: TenantDep) -> StatsResponse:
    active_workflows = db.scalar(
        select(func.count())
        .select_from(Workflow)
        .where(Workflow.tenant_id == tenant_id, Workflow.is_active.is_(True))
    ) or 0
    successful_executions = db.scalar(
        select(func.count())
        .select_from(Execution)
        .where(Execution.tenant_id == tenant_id, Execution.status == "success")
    ) or 0
    failed_executions = db.scalar(
        select(func.count())
        .select_from(Execution)
        .where(Execution.tenant_id == tenant_id, Execution.status == "failed")
    ) or 0
    connected_systems = db.scalar(
        select(func.count())
        .select_from(Connection)
        .where(Connection.tenant_id == tenant_id, Connection.is_active.is_(True))
    ) or 0
    return StatsResponse(
        active_workflows=active_workflows,
        successful_executions=successful_executions,
        failed_executions=failed_executions,
        connected_systems=connected_systems,
    )


@router.get("/executions")
def list_executions(
    db: DbDep,
    _auth: AuthDep,
    tenant_id: TenantDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    total = (
        db.scalar(
            select(func.count())
            .select_from(Execution)
            .where(Execution.tenant_id == tenant_id)
        )
        or 0
    )
    rows = db.scalars(
        select(Execution)
        .where(Execution.tenant_id == tenant_id)
        .order_by(Execution.started_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {"items": [ExecutionItem.model_validate(r) for r in rows], "total": total}


@router.get("/workflows")
def list_workflows(
    db: DbDep,
    _auth: AuthDep,
    tenant_id: TenantDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    total = (
        db.scalar(
            select(func.count())
            .select_from(Workflow)
            .where(Workflow.tenant_id == tenant_id)
        )
        or 0
    )
    rows = db.scalars(
        select(Workflow)
        .where(Workflow.tenant_id == tenant_id)
        .order_by(Workflow.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {"items": [WorkflowItem.model_validate(r) for r in rows], "total": total}


@router.get("/audit-logs")
def list_audit_logs(
    db: DbDep,
    _auth: AuthDep,
    tenant_id: TenantDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    total = (
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
        )
        or 0
    )
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.tenant_id == tenant_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {"items": [AuditLogItem.model_validate(r) for r in rows], "total": total}


@router.get("/operations/board", response_model=OperationsBoardResponse)
@router.get("/operations/board/tasks", response_model=OperationsBoardResponse)
def list_operations_tasks(
    db: DbDep,
    _auth: AuthDep,
    user: UserDep,
    tenant_id: Annotated[uuid.UUID | None, Query()] = None,
    work_type: Annotated[str | None, Query(pattern="^(administrative|financial)$")] = None,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            pattern="^(upcoming|overdue|awaiting_approval|needs_intervention|completed)$",
        ),
    ] = None,
    priority: Annotated[str | None, Query(pattern="^(urgent|high|normal)$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OperationsBoardResponse:
    """List work only for associations assigned to the authenticated employee."""
    memberships = _board_memberships(db, user)
    allowed_tenants = dict(
        db.execute(
            select(Tenant.id, Tenant.name)
            .where(Tenant.id.in_(memberships))
            .order_by(Tenant.name, Tenant.id)
        ).all()
    )

    if tenant_id is not None and tenant_id not in allowed_tenants:
        # Do not reveal whether an unassigned association exists.
        raise HTTPException(status_code=403, detail="Association is outside your assignment")

    scoped_ids = [tenant_id] if tenant_id is not None else list(allowed_tenants)
    if not scoped_ids:
        return OperationsBoardResponse(
            items=[],
            total=0,
            associations=[],
            summary=OperationsSummary(
                total_active=0, urgent=0, overdue=0, needs_intervention=0
            ),
        )

    base_filters = [OperationsTask.tenant_id.in_(scoped_ids)]
    filtered = list(base_filters)
    if work_type:
        filtered.append(OperationsTask.work_type == work_type)
    if status_filter:
        filtered.append(OperationsTask.status == status_filter)
    if priority:
        filtered.append(OperationsTask.priority == priority)

    total = db.scalar(
        select(func.count()).select_from(OperationsTask).where(*filtered)
    ) or 0
    rows = db.execute(
        select(OperationsTask, Tenant.name.label("tenant_name"))
        .join(Tenant, Tenant.id == OperationsTask.tenant_id)
        .where(*filtered)
        .order_by(
            OperationsTask.status.in_(["completed"]),
            OperationsTask.priority.in_(["normal", "high"]),
            OperationsTask.due_at,
        )
        .limit(limit)
        .offset(offset)
    ).all()

    counts = dict(
        db.execute(
            select(OperationsTask.tenant_id, func.count())
            .where(OperationsTask.tenant_id.in_(allowed_tenants))
            .group_by(OperationsTask.tenant_id)
        ).all()
    )
    summary_counts = dict(
        db.execute(
            select(OperationsTask.status, func.count())
            .where(*base_filters)
            .group_by(OperationsTask.status)
        ).all()
    )
    urgent = db.scalar(
        select(func.count())
        .select_from(OperationsTask)
        .where(
            *base_filters,
            OperationsTask.priority == "urgent",
            OperationsTask.status != "completed",
        )
    ) or 0
    active = db.scalar(
        select(func.count())
        .select_from(OperationsTask)
        .where(*base_filters, OperationsTask.status != "completed")
    ) or 0

    return OperationsBoardResponse(
        items=[
            _board_task_item(task, tenant_name, memberships[task.tenant_id])
            for task, tenant_name in rows
        ],
        total=total,
        associations=[
            AssociationItem(id=association_id, name=name, count=counts.get(association_id, 0))
            for association_id, name in allowed_tenants.items()
        ],
        summary=OperationsSummary(
            total_active=active,
            urgent=urgent,
            overdue=summary_counts.get("overdue", 0),
            needs_intervention=summary_counts.get("needs_intervention", 0),
        ),
    )


def _transition_board_task(
    task_id: uuid.UUID,
    action: str,
    body: OperationsTaskActionRequest,
    db: Session,
    user: User,
) -> OperationsTaskItem:
    memberships = _board_memberships(db, user)
    task = db.scalar(
        select(OperationsTask)
        .where(
            OperationsTask.id == task_id,
            OperationsTask.tenant_id.in_(memberships),
        )
        .with_for_update()
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.version != body.expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Task has been modified"
        )
    allowed_sources, target_status = _BOARD_TRANSITIONS[action]
    if task.status not in allowed_sources:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Invalid task transition"
        )
    role = memberships[task.tenant_id]
    if action in {"approve", "reject"} and role not in _BOARD_MANAGER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role"
        )
    note = body.note.strip() if body.note else None
    if action in {"reject", "record_intervention"} and not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An action note is required",
        )

    previous_status = task.status
    task.status = target_status
    task.version += 1
    task.last_note = note
    if action == "submit_for_approval":
        task.approval_state = "pending"
    elif action == "approve":
        task.approval_state = "approved"
    elif action == "reject":
        task.approval_state = "rejected"

    record_audit(
        db,
        action=f"operations_board.task_{action}",
        actor_type="user",
        actor_id=str(user.id),
        tenant_id=task.tenant_id,
        resource_type="operations_task",
        resource_id=str(task.id),
        metadata={
            "from_status": previous_status,
            "to_status": task.status,
            "approval_state": task.approval_state,
            "version": task.version,
            "note_recorded": note is not None,
        },
    )
    db.flush()
    tenant_name = db.scalar(select(Tenant.name).where(Tenant.id == task.tenant_id)) or ""
    return _board_task_item(task, tenant_name, role)


@router.post(
    "/operations/board/tasks/{task_id}/{action}",
    response_model=OperationsTaskItem,
    dependencies=[Depends(require_csrf)],
)
def transition_operations_board_task(
    task_id: uuid.UUID,
    action: Literal[
        "complete",
        "submit_for_approval",
        "approve",
        "reject",
        "record_intervention",
    ],
    body: OperationsTaskActionRequest,
    db: DbDep,
    _auth: AuthDep,
    user: UserDep,
) -> OperationsTaskItem:
    return _transition_board_task(task_id, action, body, db, user)

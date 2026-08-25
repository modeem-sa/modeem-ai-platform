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
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_tenant_id, require_internal_auth
from app.core.config import get_settings
from app.models import AuditLog, Connection, Execution, Workflow

router = APIRouter(prefix="/api/v1")

DbDep = Annotated[Session, Depends(get_db)]
AuthDep = Annotated[None, Depends(require_internal_auth)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]


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

"""Cookie-authenticated, membership-scoped operations task lifecycle API."""

import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.csrf import require_csrf
from app.api.deps import get_current_user, get_db
from app.content_manager.provider import (
    OpenAICompatibleProvider,
    ProviderFailureError,
    ProviderUnavailableError,
)
from app.models import (
    OperationAction,
    OperationActionHistory,
    OperationTask,
    OperationTaskHistory,
    RecurringTaskTemplate,
    Tenant,
    TenantMembership,
    User,
)
from app.models.operation_task import TASK_CATEGORIES, TASK_PRIORITIES, TASK_STATUSES
from app.operations.ai_proposal import canonical_proposal, executable_invoice_activity_proposal
from app.operations.proposals import OperationsProposalService, OverdueInvoiceSummary
from app.schemas.operations import (
    OperationActionExactRequest,
    OperationActionOut,
    OperationActionRequest,
    OperationBootstrapOut,
    OperationMemberOut,
    OperationTaskAction,
    OperationTaskCreate,
    OperationTaskListOut,
    OperationTaskOut,
    OperationTenantBootstrapOut,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])

_MANAGER_ROLES = ("owner", "admin", "manager")
_WORKER_ACTIONS = {
    "start": ("pending", "in_progress"),
    "complete": ("in_progress", "completed"),
    "submit_for_approval": ("completed", "submitted_for_approval"),
}
_DECISION_ACTIONS = {
    "approve": ("submitted_for_approval", "approved"),
    "reject": ("submitted_for_approval", "rejected"),
}
_AUDIT_ACTIONS = {
    "created": "created",
    "start": "started",
    "complete": "completed",
    "submit_for_approval": "submitted_for_approval",
    "approve": "approved",
    "reject": "rejected",
    "reopened": "reopened",
}


class RecurringTemplateRequest(BaseModel):
    tenant_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    category: str = "administrative"
    priority: str = "medium"
    frequency: str
    timezone: str = "UTC"


class RecurringTemplateOut(RecurringTemplateRequest):
    id: uuid.UUID
    enabled: bool


def _active_tenant_ids(db: Session, user: User) -> list[uuid.UUID]:
    """Return the complete server-derived board scope, never a cookie tenant."""
    if user.is_superuser:
        return [row[0] for row in db.query(Tenant.id).filter(Tenant.is_active.is_(True)).all()]
    return [
        row[0]
        for row in (
            db.query(TenantMembership.tenant_id)
            .join(Tenant, Tenant.id == TenantMembership.tenant_id)
            .filter(
                TenantMembership.user_id == user.id,
                TenantMembership.is_active.is_(True),
                Tenant.is_active.is_(True),
            )
            .all()
        )
    ]


def _role_in_tenant(db: Session, user: User, tenant_id: uuid.UUID) -> str | None:
    if user.is_superuser:
        tenant = db.get(Tenant, tenant_id)
        return "superuser" if tenant is not None and tenant.is_active else None
    membership = (
        db.query(TenantMembership)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .filter(
            TenantMembership.user_id == user.id,
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.is_active.is_(True),
            Tenant.is_active.is_(True),
        )
        .one_or_none()
    )
    return membership.role if membership is not None else None


def _is_manager(role: str | None) -> bool:
    return role == "superuser" or role in _MANAGER_ROLES


def _task_query(db: Session, tenant_ids: list[uuid.UUID]):
    return db.query(OperationTask).filter(OperationTask.tenant_id.in_(tenant_ids))


def _scoped_task(
    db: Session, user: User, task_id: uuid.UUID, *, lock: bool = False
) -> OperationTask:
    tenant_ids = _active_tenant_ids(db, user)
    query = _task_query(db, tenant_ids).filter(OperationTask.id == task_id)
    if lock:
        query = query.with_for_update()
    task = query.one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _available_actions(task: OperationTask, user: User, role: str | None) -> list[str]:
    manager = _is_manager(role)
    worker = manager or task.assigned_user_id == user.id
    if task.status == "pending" and worker:
        return ["start"]
    if task.status == "in_progress" and worker:
        return ["complete"]
    if task.status == "completed" and worker:
        return ["submit_for_approval"]
    if task.status == "submitted_for_approval" and manager:
        return ["approve", "reject"]
    if task.status == "rejected" and worker:
        return ["start"]
    return []


def _to_out(db: Session, task: OperationTask, user: User) -> OperationTaskOut:
    tenant = db.get(Tenant, task.tenant_id)
    assignee = db.get(User, task.assigned_user_id) if task.assigned_user_id else None
    role = _role_in_tenant(db, user, task.tenant_id)
    action = db.query(OperationAction).filter(
        OperationAction.task_id == task.id, OperationAction.tenant_id == task.tenant_id
    ).one_or_none()
    source_snapshot = None
    if task.source_snapshot_json:
        try:
            parsed_snapshot = json.loads(task.source_snapshot_json)
            if isinstance(parsed_snapshot, dict):
                source_snapshot = parsed_snapshot
        except json.JSONDecodeError:
            source_snapshot = None
    return OperationTaskOut(
        id=task.id,
        tenant_id=task.tenant_id,
        tenant_name=tenant.name if tenant is not None else "",
        title=task.title,
        description=task.description,
        category=task.category,
        priority=task.priority,
        status=task.status,
        assigned_user_id=task.assigned_user_id,
        assignee_name=assignee.full_name if assignee is not None else None,
        created_by_user_id=task.created_by_user_id,
        version=task.version,
        due_at=task.due_at,
        completed_at=task.completed_at,
        submitted_at=task.submitted_at,
        decided_at=task.decided_at,
        decision_note=task.decision_note,
        created_at=task.created_at,
        updated_at=task.updated_at,
        available_actions=_available_actions(task, user, role),
        source_type=task.source_type or "manual",
        source_connection_id=task.source_connection_id,
        source_record_id=task.source_record_id,
        source_signal=task.source_signal,
        source_reference=task.source_reference,
        source_snapshot=source_snapshot,
        source_sync_state=task.source_sync_state,
        source_synced_at=task.source_synced_at,
        action=(
            OperationActionOut(
                id=action.id, status=action.status, version=action.version,
                proposal=json.loads(action.proposal_json), proposal_hash=action.proposal_hash,
                approved_hash=action.approved_hash, approved_by_user_id=action.approved_by_user_id,
                approved_at=action.approved_at, attempt_count=action.attempt_count,
                error=action.error, external_activity_id=action.external_activity_id,
                verified_at=action.verified_at,
            ) if action else None
        ),
    )


def _require_assignee_membership(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    valid = (
        db.query(TenantMembership.id)
        .join(User, User.id == TenantMembership.user_id)
        .filter(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.is_active.is_(True),
            User.is_active.is_(True),
        )
        .first()
    )
    if valid is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Assigned user must have an active membership in the target tenant",
        )


def _record_history(
    db: Session,
    task: OperationTask,
    actor: User,
    *,
    action: str,
    from_status: str | None,
    note: str | None,
) -> None:
    db.add(
        OperationTaskHistory(
            task_id=task.id,
            tenant_id=task.tenant_id,
            actor_user_id=actor.id,
            action=action,
            from_status=from_status,
            to_status=task.status,
            version=task.version,
            note=note,
        )
    )
    record_audit(
        db,
        action=f"task.{_AUDIT_ACTIONS[action]}",
        actor_type="user",
        actor_id=str(actor.id),
        tenant_id=task.tenant_id,
        resource_type="operation_task",
        resource_id=str(task.id),
        metadata={
            "task_id": str(task.id),
            "from_status": from_status,
            "to_status": task.status,
            "version": task.version,
        },
    )


@router.get("/bootstrap", response_model=OperationBootstrapOut)
def operations_bootstrap(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OperationBootstrapOut:
    """Supply assignment-safe board setup data from server-derived scope."""
    if user.is_superuser:
        tenant_rows = [
            (tenant, "superuser")
            for tenant in db.query(Tenant)
            .filter(Tenant.is_active.is_(True))
            .order_by(Tenant.name.asc(), Tenant.id.asc())
            .all()
        ]
    else:
        tenant_rows = (
            db.query(Tenant, TenantMembership.role)
            .join(TenantMembership, TenantMembership.tenant_id == Tenant.id)
            .filter(
                TenantMembership.user_id == user.id,
                TenantMembership.is_active.is_(True),
                Tenant.is_active.is_(True),
            )
            .order_by(Tenant.name.asc(), Tenant.id.asc())
            .all()
        )
    tenants: list[OperationTenantBootstrapOut] = []
    for tenant, role in tenant_rows:
        can_create = _is_manager(role)
        members: list[OperationMemberOut] = []
        if can_create:
            member_rows = (
                db.query(User, TenantMembership.role)
                .join(TenantMembership, TenantMembership.user_id == User.id)
                .filter(
                    TenantMembership.tenant_id == tenant.id,
                    TenantMembership.is_active.is_(True),
                    User.is_active.is_(True),
                )
                .order_by(User.full_name.asc(), User.email.asc(), User.id.asc())
                .all()
            )
            members = [
                OperationMemberOut(
                    id=member.id,
                    full_name=member.full_name,
                    email=member.email,
                    role=member_role,
                )
                for member, member_role in member_rows
            ]
        tenants.append(
            OperationTenantBootstrapOut(
                id=tenant.id,
                name=tenant.name,
                role=role,
                can_create=can_create,
                members=members,
            )
        )
    return OperationBootstrapOut(tenants=tenants)


@router.get("/tasks", response_model=OperationTaskListOut)
def list_tasks(
    tenant_id: uuid.UUID | None = None,
    task_status: str | None = Query(default=None, alias="status"),
    category: str | None = None,
    priority: str | None = None,
    source_type: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OperationTaskListOut:
    if task_status is not None and task_status not in TASK_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid task status")
    if category is not None and category not in TASK_CATEGORIES:
        raise HTTPException(status_code=422, detail="Invalid task category")
    if priority is not None and priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=422, detail="Invalid task priority")
    if source_type is not None and source_type not in ("manual", "odoo", "recurring"):
        raise HTTPException(status_code=422, detail="Invalid task source")
    tenant_ids = _active_tenant_ids(db, user)
    if tenant_id is not None:
        tenant_ids = [tenant_id] if tenant_id in tenant_ids else []
    query = _task_query(db, tenant_ids)
    if task_status:
        query = query.filter(OperationTask.status == task_status)
    if category:
        query = query.filter(OperationTask.category == category)
    if priority:
        query = query.filter(OperationTask.priority == priority)
    if source_type:
        query = query.filter(OperationTask.source_type == source_type)
    total = query.count()
    grouped = query.with_entities(OperationTask.status, func.count(OperationTask.id)).group_by(
        OperationTask.status
    ).all()
    summary = {task_status: 0 for task_status in TASK_STATUSES}
    summary.update({row[0]: row[1] for row in grouped})
    tasks = query.order_by(OperationTask.updated_at.desc(), OperationTask.id.desc()).offset(offset).limit(limit).all()
    return OperationTaskListOut(
        items=[_to_out(db, task, user) for task in tasks], total=total, summary=summary
    )


@router.get("/tasks/{task_id}", response_model=OperationTaskOut)
def get_task(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> OperationTaskOut:
    return _to_out(db, _scoped_task(db, user, task_id), user)


@router.post(
    "/tasks",
    response_model=OperationTaskOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_task(
    body: OperationTaskCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OperationTaskOut:
    role = _role_in_tenant(db, user, body.tenant_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    if not _is_manager(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    if body.assigned_user_id is not None:
        _require_assignee_membership(db, body.tenant_id, body.assigned_user_id)
    task = OperationTask(
        tenant_id=body.tenant_id,
        title=body.title,
        description=body.description.strip() if body.description else None,
        category=body.category,
        priority=body.priority,
        due_at=body.due_at,
        assigned_user_id=body.assigned_user_id,
        created_by_user_id=user.id,
    )
    db.add(task)
    db.flush()
    _record_history(db, task, user, action="created", from_status=None, note=None)
    return _to_out(db, task, user)


def _transition(
    task_id: uuid.UUID,
    body: OperationTaskAction,
    action: str,
    user: User,
    db: Session,
) -> OperationTaskOut:
    task = _scoped_task(db, user, task_id, lock=True)
    role = _role_in_tenant(db, user, task.tenant_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.version != body.expected_version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task has been modified")
    required = _DECISION_ACTIONS.get(action) or _WORKER_ACTIONS[action]
    allowed_sources = ("pending", "rejected") if action == "start" else (required[0],)
    if task.status not in allowed_sources:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invalid task transition")
    manager = _is_manager(role)
    if action in _DECISION_ACTIONS and not manager:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    if action in _WORKER_ACTIONS and not (manager or task.assigned_user_id == user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Task is not assigned to you")
    if action == "reject" and (body.note is None or not body.note.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A rejection reason is required",
        )
    old_status = task.status
    task.status = required[1]
    task.version += 1
    now = datetime.now(UTC)
    history_action = action
    if action == "complete":
        task.completed_at = now
    elif action == "submit_for_approval":
        task.submitted_at = now
    elif action in _DECISION_ACTIONS:
        task.decided_at = now
        task.decision_note = body.note.strip() if body.note else None
    elif action == "start" and old_status == "rejected":
        history_action = "reopened"
        task.completed_at = None
        task.submitted_at = None
        task.decided_at = None
        task.decision_note = None
    db.flush()
    _record_history(
        db,
        task,
        user,
        action=history_action,
        from_status=old_status,
        note=body.note.strip() if body.note else None,
    )
    return _to_out(db, task, user)


@router.post("/tasks/{task_id}/start", response_model=OperationTaskOut, dependencies=[Depends(require_csrf)])
def start_task(task_id: uuid.UUID, body: OperationTaskAction, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OperationTaskOut:
    return _transition(task_id, body, "start", user, db)


@router.post("/tasks/{task_id}/complete", response_model=OperationTaskOut, dependencies=[Depends(require_csrf)])
def complete_task(task_id: uuid.UUID, body: OperationTaskAction, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OperationTaskOut:
    return _transition(task_id, body, "complete", user, db)


@router.post("/tasks/{task_id}/submit-for-approval", response_model=OperationTaskOut, dependencies=[Depends(require_csrf)])
def submit_task(task_id: uuid.UUID, body: OperationTaskAction, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OperationTaskOut:
    return _transition(task_id, body, "submit_for_approval", user, db)


@router.post("/tasks/{task_id}/approve", response_model=OperationTaskOut, dependencies=[Depends(require_csrf)])
def approve_task(task_id: uuid.UUID, body: OperationTaskAction, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OperationTaskOut:
    return _transition(task_id, body, "approve", user, db)


@router.post("/tasks/{task_id}/reject", response_model=OperationTaskOut, dependencies=[Depends(require_csrf)])
def reject_task(task_id: uuid.UUID, body: OperationTaskAction, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OperationTaskOut:
    return _transition(task_id, body, "reject", user, db)


def _manager_task(db: Session, user: User, task_id: uuid.UUID) -> OperationTask:
    task = _scoped_task(db, user, task_id, lock=True)
    if not _is_manager(_role_in_tenant(db, user, task.tenant_id)):
        raise HTTPException(status_code=403, detail="Insufficient role")
    return task


def _single_invoice_summary(
    *, tenant_id: uuid.UUID, snapshot: object, as_of_date: date
) -> tuple[OverdueInvoiceSummary, int, int]:
    """Derive an AI-safe aggregate from the server-sanitized Odoo snapshot."""
    if not isinstance(snapshot, dict):
        raise TypeError("invalid snapshot")
    company_id = snapshot.get("company_id")
    activity_type_id = snapshot.get("activity_type_id", 1)
    currency = snapshot.get("currency")
    due_date = snapshot.get("due_date")
    residual = snapshot.get("residual")
    if (
        isinstance(company_id, bool)
        or not isinstance(company_id, int)
        or company_id < 1
        or isinstance(activity_type_id, bool)
        or not isinstance(activity_type_id, int)
        or activity_type_id < 1
        or not isinstance(currency, str)
    ):
        raise ValueError("invalid snapshot")
    try:
        due = date.fromisoformat(str(due_date))
        amount = Decimal(str(residual))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid snapshot") from exc
    overdue_days = (as_of_date - due).days
    return (
        OverdueInvoiceSummary(
            tenant_id=tenant_id,
            as_of_date=as_of_date,
            currency=currency,
            invoice_count=1,
            customers_affected=1,
            total_overdue=amount,
            oldest_days_overdue=overdue_days,
        ),
        company_id,
        activity_type_id,
    )


def _audit_proposal_failure(db: Session, task: OperationTask, user: User, category: str) -> None:
    """Persist only a static failure category, never prompt or provider content."""
    record_audit(
        db,
        action="operation_action.generation_failed",
        actor_type="user",
        actor_id=str(user.id),
        tenant_id=task.tenant_id,
        resource_type="operation_task",
        resource_id=str(task.id),
        metadata={"status": "failed", "error_category": category},
    )
    db.commit()


def _record_action_history(
    db: Session,
    action: OperationAction,
    *,
    event: str,
    actor_type: str,
    actor_id: str,
    detail: str | None = None,
) -> None:
    """Persist server-owned lifecycle evidence; detail must be a static category."""
    db.add(
        OperationActionHistory(
            action_id=action.id,
            task_id=action.task_id,
            tenant_id=action.tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event=event,
            version=action.version,
            status=action.status,
            proposal_hash=action.proposal_hash,
            detail=detail,
        )
    )


@router.post("/tasks/{task_id}/action/generate", response_model=OperationTaskOut,
             dependencies=[Depends(require_csrf)])
def generate_action(task_id: uuid.UUID, body: OperationActionRequest,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OperationTaskOut:
    """Generate/re-generate only the server-owned invoice activity proposal."""
    task = _manager_task(db, user, task_id)
    if task.version != body.expected_version:
        raise HTTPException(status_code=409, detail="Task has been modified")
    action = (
        db.query(OperationAction)
        .filter_by(task_id=task.id, tenant_id=task.tenant_id)
        .with_for_update()
        .one_or_none()
    )
    if action is not None and action.status != "proposed":
        raise HTTPException(status_code=409, detail="Action can no longer be regenerated")
    if task.source_type != "odoo" or task.source_record_id is None or not task.source_snapshot_json:
        raise HTTPException(status_code=409, detail="Task has no supported Odoo invoice source")
    try:
        snapshot = json.loads(task.source_snapshot_json)
        summary, company_id, activity_type_id = _single_invoice_summary(
            tenant_id=task.tenant_id, snapshot=snapshot, as_of_date=datetime.now(UTC).date()
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail="Task source cannot generate an action") from exc
    try:
        provider = OpenAICompatibleProvider.from_environment()
        draft = OperationsProposalService(provider).propose(
            tenant_id=task.tenant_id, summary=summary
        )
        executable = executable_invoice_activity_proposal(
            draft,
            company_id=company_id,
            invoice_id=task.source_record_id,
            activity_type_id=activity_type_id,
        )
        payload, digest = canonical_proposal(executable)
    except ProviderUnavailableError:
        _audit_proposal_failure(db, task, user, "provider_unavailable")
        raise HTTPException(status_code=503, detail="Operations proposal service is temporarily unavailable")
    except ProviderFailureError:
        _audit_proposal_failure(db, task, user, "provider_failure")
        raise HTTPException(status_code=502, detail="Operations proposal provider failed")
    regenerated = action is not None
    if action is None:
        action = OperationAction(tenant_id=task.tenant_id, task_id=task.id, proposal_json=payload,
                                 proposal_hash=digest, idempotency_marker=uuid.uuid4().hex)
        db.add(action)
    else:
        action.proposal_json, action.proposal_hash, action.status = payload, digest, "proposed"
        action.approved_hash = action.approved_by_user_id = action.approved_at = None
        action.external_activity_id = action.verified_at = None
        action.error = None; action.version += 1
    db.flush()
    event = "regenerated" if regenerated else "generated"
    _record_action_history(
        db, action, event=event, actor_type="user", actor_id=str(user.id)
    )
    record_audit(db, action=f"operation_action.{event}", actor_type="user", actor_id=str(user.id),
                 tenant_id=task.tenant_id, resource_type="operation_task", resource_id=str(task.id), metadata={"proposal_hash": digest})
    return _to_out(db, task, user)


@router.post("/tasks/{task_id}/action/submit", response_model=OperationTaskOut, dependencies=[Depends(require_csrf)])
def submit_action(task_id: uuid.UUID, body: OperationActionRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OperationTaskOut:
    task = _manager_task(db, user, task_id)
    action = db.query(OperationAction).filter_by(task_id=task.id, tenant_id=task.tenant_id).with_for_update().one_or_none()
    if task.version != body.expected_version or action is None or action.status != "proposed":
        raise HTTPException(status_code=409, detail="Action is not ready for approval")
    action.status = "awaiting_approval"; action.version += 1
    _record_action_history(
        db, action, event="submitted", actor_type="user", actor_id=str(user.id)
    )
    record_audit(db, action="operation_action.submitted", actor_type="user", actor_id=str(user.id), tenant_id=task.tenant_id, resource_type="operation_action", resource_id=str(action.id), metadata={})
    return _to_out(db, task, user)


@router.post("/tasks/{task_id}/action/approve", response_model=OperationTaskOut, dependencies=[Depends(require_csrf)])
def approve_action(task_id: uuid.UUID, body: OperationActionRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OperationTaskOut:
    task = _manager_task(db, user, task_id)
    action = db.query(OperationAction).filter_by(task_id=task.id, tenant_id=task.tenant_id).with_for_update().one_or_none()
    if (task.version != body.expected_version or action is None or action.status != "awaiting_approval"
            or body.expected_action_version != action.version or body.expected_proposal_hash != action.proposal_hash):
        raise HTTPException(status_code=409, detail="Action has been modified")
    action.status, action.approved_hash, action.approved_by_user_id, action.approved_at = "queued", action.proposal_hash, user.id, datetime.now(UTC)
    action.version += 1
    _record_action_history(
        db, action, event="approved", actor_type="user", actor_id=str(user.id)
    )
    record_audit(db, action="operation_action.approved", actor_type="user", actor_id=str(user.id), tenant_id=task.tenant_id, resource_type="operation_action", resource_id=str(action.id), metadata={"proposal_hash": action.proposal_hash})
    return _to_out(db, task, user)


@router.post("/tasks/{task_id}/action/reject", response_model=OperationTaskOut, dependencies=[Depends(require_csrf)])
def reject_action(task_id: uuid.UUID, body: OperationActionRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OperationTaskOut:
    task = _manager_task(db, user, task_id)
    action = db.query(OperationAction).filter_by(task_id=task.id, tenant_id=task.tenant_id).with_for_update().one_or_none()
    if (task.version != body.expected_version or action is None
            or action.status != "awaiting_approval"
            or body.expected_action_version != action.version
            or body.expected_proposal_hash != action.proposal_hash):
        raise HTTPException(status_code=409, detail="Action has been modified")
    action.status = "proposed"; action.approved_hash = action.approved_by_user_id = action.approved_at = None; action.version += 1
    _record_action_history(
        db, action, event="rejected", actor_type="user", actor_id=str(user.id)
    )
    record_audit(db, action="operation_action.rejected", actor_type="user", actor_id=str(user.id), tenant_id=task.tenant_id, resource_type="operation_action", resource_id=str(action.id), metadata={})
    return _to_out(db, task, user)


@router.post(
    "/tasks/{task_id}/action/retry",
    response_model=OperationTaskOut,
    dependencies=[Depends(require_csrf)],
)
def retry_action(
    task_id: uuid.UUID,
    body: OperationActionExactRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OperationTaskOut:
    """Requeue the exact previously approved proposal without mutating its identity."""
    task = _manager_task(db, user, task_id)
    action = (
        db.query(OperationAction)
        .filter_by(task_id=task.id, tenant_id=task.tenant_id)
        .with_for_update()
        .one_or_none()
    )
    if (
        task.version != body.expected_version
        or action is None
        or action.status != "failed"
        or body.expected_action_version != action.version
        or body.expected_proposal_hash != action.proposal_hash
        or action.approved_hash != action.proposal_hash
    ):
        raise HTTPException(status_code=409, detail="Action has been modified")
    action.status = "queued"
    action.error = None
    action.version += 1
    _record_action_history(
        db, action, event="retry_queued", actor_type="user", actor_id=str(user.id)
    )
    record_audit(
        db,
        action="operation_action.retry_queued",
        actor_type="user",
        actor_id=str(user.id),
        tenant_id=task.tenant_id,
        resource_type="operation_action",
        resource_id=str(action.id),
        metadata={"proposal_hash": action.proposal_hash},
    )
    return _to_out(db, task, user)

@router.get("/recurring-templates", response_model=list[RecurringTemplateOut])
def list_recurring_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ids = _active_tenant_ids(db, user)
    return [RecurringTemplateOut(id=t.id, tenant_id=t.tenant_id, title=t.title, description=t.description, category=t.category, priority=t.priority, frequency=t.frequency, timezone=t.timezone, enabled=t.enabled) for t in db.query(RecurringTaskTemplate).filter(RecurringTaskTemplate.tenant_id.in_(ids)).all()]

@router.post("/recurring-templates", response_model=RecurringTemplateOut, dependencies=[Depends(require_csrf)])
def create_recurring_template(body: RecurringTemplateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.frequency not in ("daily", "weekly", "monthly") or body.category not in TASK_CATEGORIES or body.priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=422, detail="Invalid recurring template")
    if not _is_manager(_role_in_tenant(db, user, body.tenant_id)): raise HTTPException(status_code=403, detail="Insufficient role")
    from zoneinfo import ZoneInfo
    try: ZoneInfo(body.timezone)
    except Exception as exc: raise HTTPException(status_code=422, detail="Invalid timezone") from exc
    t = RecurringTaskTemplate(**body.model_dump(), created_by_user_id=user.id); db.add(t); db.flush()
    record_audit(db, action="recurring_template.created", actor_type="user", actor_id=str(user.id), tenant_id=t.tenant_id, resource_type="recurring_template", resource_id=str(t.id), metadata={})
    return RecurringTemplateOut(id=t.id, enabled=t.enabled, **body.model_dump())

@router.post("/recurring-templates/{template_id}/enable", response_model=RecurringTemplateOut, dependencies=[Depends(require_csrf)])
def set_recurring_template(template_id: uuid.UUID, enabled: bool, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = db.query(RecurringTaskTemplate).filter(RecurringTaskTemplate.id == template_id, RecurringTaskTemplate.tenant_id.in_(_active_tenant_ids(db, user))).one_or_none()
    if t is None: raise HTTPException(status_code=404, detail="Template not found")
    if not _is_manager(_role_in_tenant(db, user, t.tenant_id)): raise HTTPException(status_code=403, detail="Insufficient role")
    t.enabled = enabled
    return RecurringTemplateOut(id=t.id, tenant_id=t.tenant_id, title=t.title, description=t.description, category=t.category, priority=t.priority, frequency=t.frequency, timezone=t.timezone, enabled=t.enabled)
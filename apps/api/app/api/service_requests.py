"""Tenant-isolated customer requests routed only through fixed workflows."""

import hashlib
import io
import json
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.csrf import require_csrf
from app.api.deps import (
    RESOURCE_MODULES,
    allowed_odoo_modules,
    get_current_user,
    get_db,
    require_odoo_module_scope,
    require_service_scope,
)
from app.api.operations import _operations_read_page
from app.core.config import get_settings
from app.models import (
    OperationTask,
    OperationTaskHistory,
    Connection,
    ServiceRequest,
    ServiceRequestAttachment,
    ServiceRequestEvent,
    ServiceRequestMessage,
    TenantMembership,
    User,
)
from app.operations.automation_catalog import CATALOG, effective_config, get_workflow
from app.integrations.odoo.read_policies import MAX_INVENTORY_OFFSET
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1/service-requests", tags=["service-requests"])

MANAGER_ROLES = ("owner", "admin", "manager")
WORKER_ROLES = (*MANAGER_ROLES, "member")
READONLY_EMPLOYEE_ROLES = (*WORKER_ROLES, "viewer")
MAX_FILE = 10 * 1024 * 1024
MAX_TOTAL = 25 * 1024 * 1024
ALLOWED_FILES = {
    "application/pdf": (".pdf",),
    "image/png": (".png",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/webp": (".webp",),
    "text/csv": (".csv",),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (".docx",),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (".xlsx",),
}
OOXML_MARKERS = {
    ".docx": "word/document.xml",
    ".xlsx": "xl/workbook.xml",
}


class RequestBody(BaseModel):
    tenant_id: uuid.UUID
    subject: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=20000)
    requested_module: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_]{1,255}$")
    priority: str = Field(default="medium", pattern="^(low|medium|high|urgent)$")


class MessageBody(BaseModel):
    body: str = Field(min_length=1, max_length=20000)


class TransitionBody(BaseModel):
    status: str = Field(pattern="^(open|in_progress|waiting_customer|resolved|closed)$")
    expected_version: int = Field(ge=1)


class AssignmentBody(BaseModel):
    assigned_employee_id: uuid.UUID
    expected_version: int = Field(ge=1)


class ClassificationBody(BaseModel):
    requested_module: str = Field(pattern=r"^[A-Za-z0-9_]{1,255}$")
    expected_version: int = Field(ge=1)


class DispatchBody(BaseModel):
    workflow_key: str = Field(min_length=3, max_length=128)
    workflow_input: dict = Field(default_factory=dict)
    expected_version: int = Field(ge=1)


def _membership(
    db: Session, user: User, tenant_id: uuid.UUID
) -> TenantMembership | None:
    return (
        db.query(TenantMembership)
        .filter_by(user_id=user.id, tenant_id=tenant_id, is_active=True)
        .one_or_none()
    )


def _is_manager(membership: TenantMembership) -> bool:
    return membership.role in MANAGER_ROLES


def _service_for_module(module: str | None) -> str:
    if module == "account":
        return "financial"
    if module in {"hr", "hr_attendance", "hr_holidays", "hr_payroll"}:
        return "human_resources"
    if module == "purchase":
        return "purchasing"
    return "administrative"


def _require_request_scope(
    db: Session, user: User, tenant_id: uuid.UUID, requested_module: str | None
) -> None:
    require_service_scope(db, user, tenant_id, _service_for_module(requested_module))
    if requested_module:
        require_odoo_module_scope(db, user, tenant_id, requested_module)


def _can_read_employee_request(
    request: ServiceRequest, membership: TenantMembership, user: User
) -> bool:
    return membership.role in READONLY_EMPLOYEE_ROLES and (
        _is_manager(membership) or request.assigned_employee_id == user.id
    )


def _request_for_user(
    db: Session,
    user: User,
    request_id: uuid.UUID,
    *,
    lock: bool = False,
    require_worker: bool = False,
) -> tuple[ServiceRequest, TenantMembership]:
    query = db.query(ServiceRequest).filter(ServiceRequest.id == request_id)
    if lock:
        query = query.with_for_update()
    request = query.one_or_none()
    membership = _membership(db, user, request.tenant_id) if request else None
    allowed = False
    if request is not None and membership is not None:
        if membership.role == "customer":
            allowed = not require_worker and request.requester_id == user.id
        else:
            allowed = _can_read_employee_request(request, membership, user)
            if require_worker:
                allowed = allowed and membership.role in WORKER_ROLES
    if not allowed:
        raise HTTPException(status_code=404, detail="Service request not found")
    _require_request_scope(db, user, request.tenant_id, request.requested_module)
    return request, membership


def _json(value: str | None):
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _request_out(db: Session, request: ServiceRequest, *, include_events: bool = False) -> dict:
    message_rows = (
        db.query(ServiceRequestMessage, User)
        .join(User, User.id == ServiceRequestMessage.author_id)
        .filter(ServiceRequestMessage.request_id == request.id)
        .order_by(ServiceRequestMessage.created_at, ServiceRequestMessage.id)
        .all()
    )
    attachments = (
        db.query(ServiceRequestAttachment)
        .filter(ServiceRequestAttachment.request_id == request.id)
        .order_by(ServiceRequestAttachment.created_at, ServiceRequestAttachment.id)
        .all()
    )
    result = {
        "id": str(request.id),
        "tenant_id": str(request.tenant_id),
        "public_reference": request.public_reference,
        "requester_id": str(request.requester_id),
        "assigned_employee_id": (
            str(request.assigned_employee_id) if request.assigned_employee_id else None
        ),
        "subject": request.subject,
        "description": request.description,
        "requested_module": request.requested_module,
        "priority": request.priority,
        "source": request.source,
        "status": request.status,
        "workflow_key": request.workflow_key,
        "operation_task_id": (
            str(request.operation_task_id) if request.operation_task_id else None
        ),
        "automation_status": request.automation_status,
        "automation_result": _json(request.automation_result_json),
        "automation_error": request.automation_error,
        "version": request.version,
        "created_at": request.created_at,
        "updated_at": request.updated_at,
        "messages": [
            {
                "id": str(message.id),
                "author_id": str(message.author_id),
                "author_name": author.full_name,
                "body": message.body,
                "created_at": message.created_at,
            }
            for message, author in message_rows
        ],
        "attachments": [
            {
                "id": str(item.id),
                "filename": item.original_name,
                "content_type": item.content_type,
                "size": item.size,
                "sha256": item.sha256,
                "uploaded_by_id": str(item.uploaded_by_id),
                "created_at": item.created_at,
            }
            for item in attachments
        ],
    }
    if include_events:
        events = (
            db.query(ServiceRequestEvent)
            .filter(ServiceRequestEvent.request_id == request.id)
            .order_by(ServiceRequestEvent.created_at, ServiceRequestEvent.id)
            .all()
        )
        result["events"] = [
            {
                "id": str(item.id),
                "actor_id": str(item.actor_id) if item.actor_id else None,
                "event": item.event,
                "version": item.version,
                "payload": _json(item.payload_json) or {},
                "created_at": item.created_at,
            }
            for item in events
        ]
    return result


def _add_event(
    db: Session,
    request: ServiceRequest,
    user: User,
    event_name: str,
    payload: dict | None = None,
) -> None:
    db.add(
        ServiceRequestEvent(
            request_id=request.id,
            tenant_id=request.tenant_id,
            actor_id=user.id,
            event=event_name,
            version=request.version,
            payload_json=json.dumps(payload or {}, sort_keys=True, separators=(",", ":")),
        )
    )


def _audit(db: Session, request: ServiceRequest, user: User, action: str) -> None:
    record_audit(
        db,
        action=action,
        actor_type="user",
        actor_id=str(user.id),
        tenant_id=request.tenant_id,
        resource_type="service_request",
        resource_id=str(request.id),
        metadata={},
    )


def _live_modules(
    db: Session,
    user: User,
    tenant_id: uuid.UUID,
    *,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    if not user.is_superuser and db.query(TenantMembership.id).filter(
        TenantMembership.user_id == user.id,
        TenantMembership.tenant_id == tenant_id,
        TenantMembership.is_active.is_(True),
    ).first() is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    connection = db.query(Connection).filter(
        Connection.tenant_id == tenant_id,
        Connection.provider == "odoo",
        Connection.is_active.is_(True),
        Connection.status != "disabled",
        Connection.last_test_status == "success",
        Connection.selected_transport.in_(("xmlrpc", "json2")),
        Connection.encrypted_credentials.is_not(None),
        Connection.encryption_version.is_not(None),
    ).order_by(Connection.created_at.desc(), Connection.id.desc()).first()
    if connection is None:
        raise HTTPException(status_code=409, detail="Tenant has no active tested Odoo connection")
    filters = [{"field": "name", "operator": "=", "value": search}] if search else []
    allowed_modules = allowed_odoo_modules(db, user, tenant_id)
    if allowed_modules is not None:
        filters.append(
            {"field": "name", "operator": "in", "value": sorted(allowed_modules)}
            if allowed_modules
            else {"field": "id", "operator": "=", "value": -1}
        )
    return _operations_read_page(
        connection,
        resource="installed_modules",
        filters=filters,
        limit=limit,
        offset=offset,
        company_scoped=False,
    )


def _require_live_module(
    db: Session, user: User, tenant_id: uuid.UUID, technical_name: str
) -> dict:
    _require_request_scope(db, user, tenant_id, technical_name)
    require_odoo_module_scope(db, user, tenant_id, technical_name)
    page = _live_modules(db, user, tenant_id, search=technical_name, limit=1)
    record = next(
        (item for item in page.get("records", []) if item.get("name") == technical_name),
        None,
    )
    if record is None:
        raise HTTPException(status_code=409, detail="Required Odoo module is not installed")
    return record


def _safe_filename(filename: str | None, content_type: str | None) -> tuple[str, str]:
    name = (filename or "").strip()
    if (
        not name
        or len(name) > 255
        or Path(name).name != name
        or "/" in name
        or "\\" in name
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or content_type not in ALLOWED_FILES
    ):
        raise HTTPException(status_code=422, detail="Unsupported or unsafe attachment")
    extension = Path(name).suffix.lower()
    if extension not in ALLOWED_FILES[content_type]:
        raise HTTPException(status_code=422, detail="Attachment type does not match filename")
    return name, extension


def _validate_content(raw: bytes, content_type: str, extension: str) -> None:
    valid = bool(raw)
    if content_type == "application/pdf":
        valid = raw.startswith(b"%PDF-")
    elif content_type == "image/png":
        valid = raw.startswith(b"\x89PNG\r\n\x1a\n")
    elif content_type == "image/jpeg":
        valid = raw.startswith(b"\xff\xd8\xff")
    elif content_type == "image/webp":
        valid = len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    elif content_type == "text/csv":
        try:
            raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            valid = False
    elif extension in OOXML_MARKERS:
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names = set(archive.namelist())
                valid = "[Content_Types].xml" in names and OOXML_MARKERS[extension] in names
        except (zipfile.BadZipFile, OSError):
            valid = False
    if not valid:
        raise HTTPException(status_code=422, detail="Attachment content is invalid")


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
def create_request(
    body: RequestBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    membership = _membership(db, user, body.tenant_id)
    if membership is None:
        raise HTTPException(status_code=403, detail="No active membership for this tenant")
    if membership.role != "customer":
        raise HTTPException(status_code=403, detail="Customer membership required")
    _require_request_scope(db, user, body.tenant_id, body.requested_module)
    if body.requested_module:
        _require_live_module(db, user, body.tenant_id, body.requested_module)
    employee = (
        db.query(TenantMembership)
        .join(User, User.id == TenantMembership.user_id)
        .filter(
            TenantMembership.tenant_id == body.tenant_id,
            TenantMembership.is_active.is_(True),
            TenantMembership.role.in_(WORKER_ROLES),
            User.is_active.is_(True),
        )
        .order_by(TenantMembership.role, User.id)
        .first()
    )
    request = ServiceRequest(
        tenant_id=body.tenant_id,
        requester_id=user.id,
        assigned_employee_id=employee.user_id if employee else None,
        subject=body.subject.strip(),
        description=body.description.strip(),
        requested_module=body.requested_module,
        priority=body.priority,
        source="portal",
        status="open",
        automation_status="none",
        public_reference=f"SR-{uuid.uuid4().hex[:10].upper()}",
        version=1,
    )
    db.add(request)
    db.flush()
    _add_event(db, request, user, "created")
    _audit(db, request, user, "service_request.created")
    return _request_out(db, request)


@router.get("")
def list_requests(
    tenant_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    membership = _membership(db, user, tenant_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    query = db.query(ServiceRequest).filter(ServiceRequest.tenant_id == tenant_id)
    if membership.role == "customer":
        query = query.filter(ServiceRequest.requester_id == user.id)
    elif membership.role in MANAGER_ROLES:
        pass
    elif membership.role in READONLY_EMPLOYEE_ROLES:
        query = query.filter(ServiceRequest.assigned_employee_id == user.id)
    else:
        raise HTTPException(status_code=403, detail="Insufficient role")
    rows = []
    for item in query.order_by(ServiceRequest.created_at.desc()).all():
        try:
            _require_request_scope(db, user, item.tenant_id, item.requested_module)
        except HTTPException as exc:
            if exc.status_code == 403:
                continue
            raise
        rows.append(item)
    return {"items": [_request_out(db, item) for item in rows]}


@router.get("/inbox")
def employee_inbox(
    tenant_id: uuid.UUID,
    include_all: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    membership = _membership(db, user, tenant_id)
    if membership is None or membership.role not in READONLY_EMPLOYEE_ROLES:
        raise HTTPException(status_code=403, detail="Employee membership required")
    query = db.query(ServiceRequest).filter(ServiceRequest.tenant_id == tenant_id)
    if not (include_all and _is_manager(membership)):
        query = query.filter(ServiceRequest.assigned_employee_id == user.id)
    rows = []
    for item in query.order_by(ServiceRequest.created_at.desc()).all():
        try:
            _require_request_scope(db, user, item.tenant_id, item.requested_module)
        except HTTPException as exc:
            if exc.status_code == 403:
                continue
            raise
        rows.append(item)
    return {"items": [_request_out(db, item) for item in rows]}


@router.get("/modules")
def request_modules(
    tenant_id: uuid.UUID,
    search: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=50, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=MAX_INVENTORY_OFFSET),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if _membership(db, user, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    require_service_scope(db, user, tenant_id, "administrative")
    page = _live_modules(db, user, tenant_id, search=search, limit=limit, offset=offset)
    for record in page.get("records", []):
        module = record.get("name")
        matching = [workflow for workflow in CATALOG if workflow.required_odoo_module == module]
        record["capabilities"] = {
            "installed": True,
            "accepts_requests": bool(matching),
            "read_supported": module in set(RESOURCE_MODULES.values()),
            "execution_supported": any(
                bool(effective_config(db, tenant_id, workflow.key)["enabled"])
                and all(step.executor_available for step in workflow.steps)
                for workflow in matching
            ),
        }
    return page


@router.get("/assignees")
def request_assignees(
    tenant_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    membership = _membership(db, user, tenant_id)
    if membership is None or not _is_manager(membership):
        raise HTTPException(status_code=403, detail="Manager membership required")
    rows = (
        db.query(TenantMembership, User)
        .join(User, User.id == TenantMembership.user_id)
        .filter(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.is_active.is_(True),
            TenantMembership.role.in_(WORKER_ROLES),
            User.is_active.is_(True),
        )
        .order_by(User.full_name, User.email)
        .all()
    )
    return {
        "items": [
            {
                "user_id": str(employee.id),
                "full_name": employee.full_name,
                "email": employee.email,
                "role": employee_membership.role,
            }
            for employee_membership, employee in rows
        ]
    }


@router.get("/{request_id}")
def request_detail(
    request_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, membership = _request_for_user(db, user, request_id)
    return _request_out(db, request, include_events=membership.role != "customer")


@router.post("/{request_id}/messages", dependencies=[Depends(require_csrf)])
def add_message(
    request_id: uuid.UUID,
    body: MessageBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, membership = _request_for_user(db, user, request_id, lock=True)
    if membership.role == "viewer":
        raise HTTPException(status_code=403, detail="Read-only employee role")
    db.add(
        ServiceRequestMessage(
            request_id=request.id,
            tenant_id=request.tenant_id,
            author_id=user.id,
            body=body.body.strip(),
        )
    )
    request.version += 1
    _add_event(db, request, user, "message_added")
    _audit(db, request, user, "service_request.message_added")
    db.flush()
    return _request_out(db, request, include_events=membership.role != "customer")


@router.post("/{request_id}/attachments", dependencies=[Depends(require_csrf)])
async def add_attachment(
    request_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, membership = _request_for_user(db, user, request_id, lock=True)
    if membership.role == "viewer":
        raise HTTPException(status_code=403, detail="Read-only employee role")
    filename, extension = _safe_filename(file.filename, file.content_type)
    raw = await file.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise HTTPException(status_code=422, detail="Attachment exceeds size limit")
    _validate_content(raw, file.content_type, extension)
    used = (
        db.query(func.coalesce(func.sum(ServiceRequestAttachment.size), 0))
        .filter(ServiceRequestAttachment.request_id == request.id)
        .scalar()
    )
    if int(used or 0) + len(raw) > MAX_TOTAL:
        raise HTTPException(status_code=422, detail="Request attachment total exceeds limit")
    attachment_id = uuid.uuid4()
    storage_key = f"{request.tenant_id}/{request.id}/{attachment_id.hex}"
    root = Path(get_settings().service_request_upload_dir).resolve()
    path = (root / storage_key).resolve()
    if root not in path.parents:
        raise HTTPException(status_code=500, detail="Invalid attachment storage path")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o600)
    item = ServiceRequestAttachment(
        id=attachment_id,
        request_id=request.id,
        tenant_id=request.tenant_id,
        uploaded_by_id=user.id,
        original_name=filename,
        storage_key=storage_key,
        content_type=file.content_type,
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    try:
        db.add(item)
        request.version += 1
        _add_event(db, request, user, "attachment_added", {"sha256": item.sha256})
        _audit(db, request, user, "service_request.attachment_added")
        db.flush()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    return {
        "id": str(item.id),
        "filename": item.original_name,
        "content_type": item.content_type,
        "size": item.size,
        "sha256": item.sha256,
        "created_at": item.created_at,
    }


@router.get("/{request_id}/attachments/{attachment_id}")
def download_attachment(
    request_id: uuid.UUID,
    attachment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    request, _membership_row = _request_for_user(db, user, request_id)
    item = (
        db.query(ServiceRequestAttachment)
        .filter_by(id=attachment_id, request_id=request.id, tenant_id=request.tenant_id)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    root = Path(get_settings().service_request_upload_dir).resolve()
    path = (root / item.storage_key).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(path, media_type=item.content_type, filename=item.original_name)


@router.post("/{request_id}/assignment", dependencies=[Depends(require_csrf)])
def assign_request(
    request_id: uuid.UUID,
    body: AssignmentBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request = (
        db.query(ServiceRequest)
        .filter(ServiceRequest.id == request_id)
        .with_for_update()
        .one_or_none()
    )
    membership = _membership(db, user, request.tenant_id) if request else None
    if request is None or membership is None or not _is_manager(membership):
        raise HTTPException(status_code=404, detail="Service request not found")
    assignee = (
        db.query(TenantMembership)
        .join(User, User.id == TenantMembership.user_id)
        .filter(
            TenantMembership.tenant_id == request.tenant_id,
            TenantMembership.user_id == body.assigned_employee_id,
            TenantMembership.is_active.is_(True),
            TenantMembership.role.in_(WORKER_ROLES),
            User.is_active.is_(True),
        )
        .one_or_none()
    )
    if assignee is None:
        raise HTTPException(status_code=422, detail="Assignee is not an active tenant employee")
    if request.version != body.expected_version:
        raise HTTPException(status_code=409, detail="Request has changed")
    old = request.assigned_employee_id
    request.assigned_employee_id = assignee.user_id
    request.version += 1
    _add_event(
        db,
        request,
        user,
        "assigned",
        {
            "from": str(old) if old else None,
            "to": str(assignee.user_id),
        },
    )
    _audit(db, request, user, "service_request.assigned")
    return _request_out(db, request, include_events=True)


@router.post("/{request_id}/classification", dependencies=[Depends(require_csrf)])
def classify_request(
    request_id: uuid.UUID,
    body: ClassificationBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _membership_row = _request_for_user(
        db, user, request_id, lock=True, require_worker=True
    )
    if request.version != body.expected_version:
        raise HTTPException(status_code=409, detail="Request has changed")
    _require_live_module(db, user, request.tenant_id, body.requested_module)
    old = request.requested_module
    request.requested_module = body.requested_module
    request.version += 1
    _add_event(
        db,
        request,
        user,
        "classified",
        {"from": old, "to": request.requested_module},
    )
    _audit(db, request, user, "service_request.classified")
    return _request_out(db, request, include_events=True)


@router.post("/{request_id}/status", dependencies=[Depends(require_csrf)])
def change_status(
    request_id: uuid.UUID,
    body: TransitionBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, membership = _request_for_user(db, user, request_id, lock=True)
    transitions = {
        "customer": {"open": ("closed",), "resolved": ("closed", "open"), "closed": ("open",)},
        "employee": {
            "open": ("in_progress", "resolved", "closed"),
            "in_progress": ("waiting_customer", "resolved", "closed"),
            "waiting_customer": ("in_progress", "closed"),
            "resolved": ("closed", "open"),
            "closed": ("open",),
        },
    }
    actor = "customer" if membership.role == "customer" else "employee"
    if membership.role == "viewer":
        raise HTTPException(status_code=403, detail="Read-only employee role")
    if (
        request.version != body.expected_version
        or body.status not in transitions[actor].get(request.status, ())
    ):
        raise HTTPException(
            status_code=409, detail="Invalid status transition or stale request"
        )
    old = request.status
    request.status = body.status
    request.version += 1
    _add_event(db, request, user, "status_changed", {"from": old, "to": request.status})
    _audit(db, request, user, "service_request.status_changed")
    return _request_out(db, request, include_events=actor == "employee")


@router.post("/{request_id}/dispatch", dependencies=[Depends(require_csrf)])
def dispatch_request(
    request_id: uuid.UUID,
    body: DispatchBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _membership_row = _request_for_user(
        db, user, request_id, lock=True, require_worker=True
    )
    workflow = get_workflow(body.workflow_key)
    if workflow is None:
        raise HTTPException(status_code=422, detail="Unknown server workflow")
    try:
        encoded_input = json.dumps(
            body.workflow_input, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Workflow input must be JSON") from exc
    if len(encoded_input) > 4000:
        raise HTTPException(status_code=422, detail="Workflow input is too large")
    config = effective_config(db, request.tenant_id, workflow.key)
    modes = config["step_modes"]
    if (
        not config["enabled"]
        or not any(mode != "manual" for mode in modes.values())
        or any(
            modes[step.key] != "manual" and not step.executor_available
            for step in workflow.steps
        )
    ):
        raise HTTPException(status_code=409, detail="Workflow executor is unavailable")
    if request.version != body.expected_version:
        raise HTTPException(status_code=409, detail="Request has changed")
    if request.operation_task_id is not None:
        if request.workflow_key == workflow.key:
            return _request_out(db, request, include_events=True)
        raise HTTPException(
            status_code=409, detail="Request was already dispatched to another workflow"
        )
    installed_module = None
    required_service = {
        "finance": "financial",
        "human_resources": "human_resources",
        "purchasing": "purchasing",
    }.get(workflow.module, "administrative")
    require_service_scope(db, user, request.tenant_id, required_service)
    if workflow.required_odoo_module:
        installed_module = _require_live_module(
            db, user, request.tenant_id, workflow.required_odoo_module
        )
    task = OperationTask(
        tenant_id=request.tenant_id,
        title=request.subject,
        description=request.description,
        category={
            "finance": "financial",
            "human_resources": "human_resources",
        }.get(workflow.module, "administrative"),
        procedure_type=workflow.service,
        priority=request.priority,
        status="pending",
        assigned_user_id=request.assigned_employee_id or user.id,
        created_by_user_id=user.id,
        request_data_json=json.dumps(
            {
                "service_request_id": str(request.id),
                "workflow_input": body.workflow_input,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        source_type="service_request",
        source_reference=request.public_reference,
    )
    db.add(task)
    db.flush()
    db.add(
        OperationTaskHistory(
            task_id=task.id,
            tenant_id=task.tenant_id,
            actor_user_id=user.id,
            action="created_from_service_request",
            from_status=None,
            to_status="pending",
            version=task.version,
        )
    )
    request.workflow_key = workflow.key
    request.workflow_config_version = int(config["version"])
    request.operation_task_id = task.id
    request.installed_modules_json = json.dumps(
        [installed_module] if installed_module else [],
        sort_keys=True,
        separators=(",", ":"),
    )
    request.automation_status = "queued"
    request.automation_queued_at = datetime.now(UTC)
    request.version += 1
    _add_event(
        db,
        request,
        user,
        "dispatch_queued",
        {"workflow_key": workflow.key, "task_id": str(task.id)},
    )
    _audit(db, request, user, "service_request.dispatch_queued")
    return _request_out(db, request, include_events=True)
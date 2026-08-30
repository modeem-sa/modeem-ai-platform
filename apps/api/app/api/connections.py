"""Tenant-scoped Connection CRUD (Phase 2B).

- Every query scopes id AND tenant_id in one ORM filter (no fetch-then-check).
- 404 for cross-tenant access so other tenants' UUIDs leak nothing.
- Writes: owner/admin only, CSRF required. Reads: any active member.
- Responses never contain credentials, ciphertext, or nonces.
- NO external/Odoo network call exists anywhere in this module.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.csrf import require_csrf
from app.api.deps import (
    TenantContext,
    get_current_tenant,
    get_current_user,
    get_db,
    require_role,
)
from app.core.config import get_settings
from app.models import (
    Connection,
    OperationAction,
    OperationActionHistory,
    OperationTask,
    User,
)
from app.operations.odoo_sync import scan_overdue_invoices
from app.schemas.connections import (
    ConnectionCreate,
    ConnectionOut,
    ConnectionTestResult,
    ConnectionUpdate,
    validate_base_url,
)
from app.schemas.odoo_read import ReadPreviewRequest, ReadPreviewResponse
from app.services.audit import record_audit
from app.services.connection_auth import AuthMaterialError, resolve_auth_material
from app.services.credential_crypto import (
    CredentialDecryptionError,
    EncryptionConfigError,
    decrypt_credentials,
    encrypt_credentials,
)

router = APIRouter(prefix="/api/v1")

_WRITE_ROLES = ("owner", "admin")


def _to_out(conn: Connection) -> ConnectionOut:
    return ConnectionOut(
        id=conn.id,
        name=conn.name,
        provider=conn.provider,
        base_url=conn.base_url,
        database_name=conn.database_name,
        username=conn.username,
        odoo_company_id=conn.odoo_company_id,
        status=conn.status,
        is_active=conn.is_active,
        has_credentials=conn.encrypted_credentials is not None,
        auth_mode=conn.auth_mode,
        detected_odoo_version=conn.detected_odoo_version,
        detected_odoo_major=conn.detected_odoo_major,
        detected_edition=conn.detected_edition,
        selected_transport=conn.selected_transport,
        last_tested_at=conn.last_tested_at,
        last_test_status=conn.last_test_status,
        last_test_error_code=conn.last_test_error_code,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


def _scoped_get(
    db: Session, ctx: TenantContext, connection_id: uuid.UUID, *, lock: bool = False
) -> Connection:
    query = (
        db.query(Connection)
        .filter(Connection.id == connection_id, Connection.tenant_id == ctx.tenant.id)
    )
    if lock:
        query = query.with_for_update()
    conn = query.first()
    if conn is None:
        # 404 (not 403) so existence in another tenant is not leaked.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found"
        )
    return conn


def _checked_base_url(value: str) -> str:
    settings = get_settings()
    try:
        return validate_base_url(
            value, require_https=settings.environment == "production"
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


def _invalidate_test_metadata(conn: Connection) -> None:
    """Reset connectivity-test results when connectivity-sensitive
    configuration changes (base_url, database_name, auth_mode, credentials).
    A name-only change never triggers this."""
    conn.last_test_status = None
    conn.last_test_error_code = None
    conn.last_tested_at = None
    conn.detected_odoo_version = None
    conn.detected_odoo_major = None
    conn.detected_edition = None
    conn.selected_transport = None
    conn.capabilities_json = None


def _encrypt_or_503(payload: dict, *, tenant_id: uuid.UUID, connection_id: uuid.UUID):
    try:
        return encrypt_credentials(
            payload, tenant_id=tenant_id, connection_id=connection_id
        )
    except EncryptionConfigError as exc:
        # Clear failure when the encryption key is not configured (dev).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.get("/connections", response_model=list[ConnectionOut])
def list_connections(
    ctx: TenantContext = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> list[ConnectionOut]:
    rows = (
        db.query(Connection)
        .filter(Connection.tenant_id == ctx.tenant.id)
        .order_by(Connection.created_at.desc())
        .all()
    )
    return [_to_out(c) for c in rows]


@router.get("/connections/{connection_id}", response_model=ConnectionOut)
def get_connection(
    connection_id: uuid.UUID,
    ctx: TenantContext = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    return _to_out(_scoped_get(db, ctx, connection_id))


@router.post(
    "/connections",
    response_model=ConnectionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_connection(
    body: ConnectionCreate,
    ctx: TenantContext = Depends(require_role(*_WRITE_ROLES)),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    base_url = _checked_base_url(body.base_url)

    duplicate = (
        db.query(Connection)
        .filter(Connection.tenant_id == ctx.tenant.id, Connection.name == body.name)
        .first()
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A connection with this name already exists",
        )

    connection_id = uuid.uuid4()
    blob, version = _encrypt_or_503(
        body.credentials.model_dump(),
        tenant_id=ctx.tenant.id,
        connection_id=connection_id,
    )

    conn = Connection(
        id=connection_id,
        tenant_id=ctx.tenant.id,
        name=body.name,
        provider=body.provider,
        base_url=base_url,
        database_name=body.database_name,
        username=body.username,
        auth_mode=body.auth_mode,
        odoo_company_id=body.odoo_company_id,
        encrypted_credentials=blob,
        encryption_version=version,
        status="configured",
        created_by_user_id=actor.id,
        updated_by_user_id=actor.id,
    )
    db.add(conn)
    db.flush()
    record_audit(
        db,
        action="connection.created",
        actor_type="user",
        actor_id=str(actor.id),
        tenant_id=ctx.tenant.id,
        resource_type="connection",
        resource_id=str(conn.id),
        metadata={"provider": conn.provider, "name": conn.name},
    )
    return _to_out(conn)


@router.patch(
    "/connections/{connection_id}",
    response_model=ConnectionOut,
    dependencies=[Depends(require_csrf)],
)
def update_connection(
    connection_id: uuid.UUID,
    body: ConnectionUpdate,
    ctx: TenantContext = Depends(require_role(*_WRITE_ROLES)),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    conn = _scoped_get(db, ctx, connection_id, lock=True)
    provided = body.model_fields_set
    connectivity_changed = False
    company_scope_changed = False

    if body.name is not None and body.name != conn.name:
        new_name = body.name
        duplicate = (
            db.query(Connection)
            .filter(
                Connection.tenant_id == ctx.tenant.id,
                Connection.name == new_name,
                Connection.id != conn.id,
            )
            .first()
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A connection with this name already exists",
            )
        conn.name = new_name
    if body.base_url is not None:
        new_base_url = _checked_base_url(body.base_url)
        if new_base_url != conn.base_url:
            connectivity_changed = True
        conn.base_url = new_base_url
    # Omitted field -> preserve; explicit JSON null -> clear (nullable metadata).
    if "database_name" in provided:
        if body.database_name != conn.database_name:
            connectivity_changed = True
        conn.database_name = body.database_name
    if "username" in provided:
        # The canonical login cannot be cleared; same normalized value is
        # not connectivity-sensitive.
        if body.username is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="username cannot be cleared",
            )
        if body.username != conn.username:
            connectivity_changed = True
        conn.username = body.username
    if body.status is not None:
        conn.status = body.status
        conn.is_active = body.status != "disabled"
    if body.auth_mode is not None:
        if body.auth_mode != conn.auth_mode:
            connectivity_changed = True
        conn.auth_mode = body.auth_mode
    if "odoo_company_id" in provided:
        company_scope_changed = body.odoo_company_id != conn.odoo_company_id
        conn.odoo_company_id = body.odoo_company_id

    credentials_changed = False
    if body.credentials is not None:
        blob, version = _encrypt_or_503(
            body.credentials.model_dump(),
            tenant_id=ctx.tenant.id,
            connection_id=conn.id,
        )
        conn.encrypted_credentials = blob
        conn.encryption_version = version
        credentials_changed = True
        connectivity_changed = True
    # If no new credential is supplied, the existing encrypted blob is kept.

    if connectivity_changed:
        # A stale successful test must never authorize reads against a
        # changed endpoint / database / auth mode / credential set.
        _invalidate_test_metadata(conn)

    invalidated_count = 0
    if company_scope_changed:
        queued_actions = (
            db.query(OperationAction)
            .join(
                OperationTask,
                (OperationTask.id == OperationAction.task_id)
                & (OperationTask.tenant_id == OperationAction.tenant_id),
            )
            .filter(
                OperationTask.source_connection_id == conn.id,
                OperationAction.tenant_id == ctx.tenant.id,
                OperationAction.status == "queued",
            )
            .with_for_update(of=OperationAction)
            .all()
        )
        for action in queued_actions:
            action.status = "failed"
            action.error = "company_scope_changed"
            action.version += 1
            db.add(
                OperationActionHistory(
                    action_id=action.id,
                    task_id=action.task_id,
                    tenant_id=action.tenant_id,
                    actor_type="system",
                    actor_id="connection-scope-change",
                    event="failed",
                    version=action.version,
                    status=action.status,
                    proposal_hash=action.proposal_hash,
                    detail="company_scope_changed",
                )
            )
        invalidated_count = len(queued_actions)
        record_audit(
            db,
            action="connection.queued_actions_invalidated",
            actor_type="user",
            actor_id=str(actor.id),
            tenant_id=ctx.tenant.id,
            resource_type="connection",
            resource_id=str(conn.id),
            metadata={
                "reason": "company_scope_changed",
                "invalidated_count": invalidated_count,
            },
        )

    conn.updated_by_user_id = actor.id
    record_audit(
        db,
        action=(
            "connection.credentials_replaced" if credentials_changed else "connection.updated"
        ),
        actor_type="user",
        actor_id=str(actor.id),
        tenant_id=ctx.tenant.id,
        resource_type="connection",
        resource_id=str(conn.id),
        metadata={
            "provider": conn.provider,
            "name": conn.name,
            "credentials_changed": credentials_changed,
            "company_scope_changed": company_scope_changed,
            "invalidated_count": invalidated_count,
        },
    )
    db.flush()
    return _to_out(conn)


@router.post(
    "/connections/{connection_id}/test",
    response_model=ConnectionTestResult,
    dependencies=[Depends(require_csrf)],
)
def test_connection(
    connection_id: uuid.UUID,
    ctx: TenantContext = Depends(require_role(*_WRITE_ROLES)),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConnectionTestResult:
    """Technical connectivity test — version/auth/capability/edition probes
    only. Reads NO business data. Returns safe metadata, never secrets or
    raw upstream errors."""
    from datetime import UTC, datetime

    from app.integrations.odoo import connector as odoo_connector

    conn = _scoped_get(db, ctx, connection_id)
    if not conn.is_active or conn.status == "disabled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connection is disabled",
        )
    if conn.encrypted_credentials is None or conn.encryption_version is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connection has no stored credentials",
        )
    try:
        credentials = decrypt_credentials(
            conn.encrypted_credentials,
            tenant_id=conn.tenant_id,
            connection_id=conn.id,
            encryption_version=conn.encryption_version,
        )
    except EncryptionConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except CredentialDecryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stored credentials cannot be decrypted",
        ) from exc

    try:
        auth = resolve_auth_material(conn.username, credentials)
    except AuthMaterialError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=exc.message
        ) from exc
    finally:
        del credentials

    settings = get_settings()
    outcome = odoo_connector.test_connection(
        base_url=conn.base_url,
        database=conn.database_name,
        auth_mode=conn.auth_mode,
        login=auth.login,
        secret=auth.secret,
        environment=settings.environment,
    )
    # Minimize plaintext credential lifetime.
    del auth

    tested_at = datetime.now(UTC)
    conn.last_tested_at = tested_at
    if outcome.success:
        conn.last_test_status = "success"
        conn.last_test_error_code = None
        conn.detected_odoo_version = outcome.odoo_version
        conn.detected_odoo_major = outcome.odoo_major
        conn.detected_edition = outcome.edition
        conn.selected_transport = outcome.transport
        import json as _json

        conn.capabilities_json = _json.dumps(outcome.capabilities)
    else:
        # Never overwrite previously known good metadata with failure data.
        conn.last_test_status = "error"
        conn.last_test_error_code = outcome.error_code

    record_audit(
        db,
        action=(
            "connection.test_succeeded" if outcome.success else "connection.test_failed"
        ),
        actor_type="user",
        actor_id=str(actor.id),
        tenant_id=ctx.tenant.id,
        resource_type="connection",
        resource_id=str(conn.id),
        metadata={
            "provider": conn.provider,
            "detected_odoo_version": outcome.odoo_version,
            "selected_transport": outcome.transport,
            "error_code": outcome.error_code,
        },
    )
    db.flush()
    return ConnectionTestResult(
        success=outcome.success,
        error_code=outcome.error_code,
        odoo_version=outcome.odoo_version,
        odoo_major=outcome.odoo_major,
        edition=outcome.edition if outcome.success else None,
        transport=outcome.transport if outcome.success else None,
        capabilities=outcome.capabilities if outcome.success else None,
        tested_at=tested_at,
    )


@router.post(
    "/connections/{connection_id}/read-preview",
    response_model=ReadPreviewResponse,
    dependencies=[Depends(require_csrf)],
)
def read_preview(
    connection_id: uuid.UUID,
    body: ReadPreviewRequest,
    ctx: TenantContext = Depends(require_role(*_WRITE_ROLES)),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReadPreviewResponse:
    """Policy-driven READ-ONLY preview of ONE bounded page. POST is used
    intentionally so filters never appear in URLs. Owner/admin only in
    Phase 2D. No Odoo record is ever persisted locally."""
    from app.integrations.odoo import reader as odoo_reader
    from app.integrations.odoo.errors import ConnectorError
    from app.integrations.odoo.reader import ReadPolicyError, ResourceUnavailableError

    conn = _scoped_get(db, ctx, connection_id)
    if not conn.is_active or conn.status == "disabled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Connection is disabled"
        )
    if conn.provider != "odoo":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Unsupported provider"
        )
    if conn.encrypted_credentials is None or conn.encryption_version is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connection has no stored credentials",
        )
    if conn.last_test_status != "success":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connection must pass Test Connection before data preview",
        )
    if conn.selected_transport not in ("xmlrpc", "json2"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connection must be re-tested before data preview",
        )

    try:
        credentials = decrypt_credentials(
            conn.encrypted_credentials,
            tenant_id=conn.tenant_id,
            connection_id=conn.id,
            encryption_version=conn.encryption_version,
        )
    except EncryptionConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except CredentialDecryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stored credentials cannot be decrypted",
        ) from exc

    try:
        auth = resolve_auth_material(conn.username, credentials)
    except AuthMaterialError as exc:
        # Fails safely BEFORE any network activity; static message only.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=exc.message
        ) from exc
    finally:
        del credentials

    settings = get_settings()

    def _audit(*, success: bool, returned_count: int | None, error_code: str | None):
        # Safe metadata only: NEVER record content, filter values,
        # credentials, or raw domains.
        record_audit(
            db,
            action=(
                "connection.read_preview_succeeded"
                if success
                else "connection.read_preview_failed"
            ),
            actor_type="user",
            actor_id=str(actor.id),
            tenant_id=ctx.tenant.id,
            resource_type="connection",
            resource_id=str(conn.id),
            metadata={
                "resource": body.resource,
                "transport": conn.selected_transport,
                "requested_limit": body.limit,
                "returned_count": returned_count,
                "error_code": error_code,
            },
        )

    try:
        page = odoo_reader.read_page(
            base_url=conn.base_url,
            database=conn.database_name,
            transport=conn.selected_transport,
            login=auth.login,
            secret=auth.secret,
            environment=settings.environment,
            resource=body.resource,
            fields=body.fields,
            filters=(
                [f.model_dump() for f in body.filters] if body.filters else None
            ),
            limit=body.limit,
            offset=body.offset,
            order_by=body.order_by,
            order_direction=body.order_direction,
            company_id=body.company_id,
        )
    except ReadPolicyError as exc:
        # Modeem-side policy violation: safe static message, never sent
        # to Odoo and no upstream call was made.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
        ) from exc
    except ResourceUnavailableError as exc:
        _audit(success=False, returned_count=None, error_code="resource_unavailable")
        db.flush()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=exc.message
        ) from exc
    except ConnectorError as exc:
        _audit(success=False, returned_count=None, error_code=exc.code)
        db.flush()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": exc.code},
        ) from exc
    finally:
        del auth

    _audit(success=True, returned_count=page["returned_count"], error_code=None)
    db.flush()
    return ReadPreviewResponse(**page)


@router.post("/connections/{connection_id}/sync-overdue-invoices", dependencies=[Depends(require_csrf)])
def sync_overdue_invoices(
    connection_id: uuid.UUID,
    ctx: TenantContext = Depends(require_role("owner", "admin", "manager")),
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict[str, int]:
    """Manager-triggered scan of a fixed customer-invoice signal only."""
    conn = _scoped_get(db, ctx, connection_id)
    try:
        if conn.odoo_company_id is None:
            raise ValueError("Connection has no approved Odoo company scope")
        created = scan_overdue_invoices(db, connection=conn, company_id=conn.odoo_company_id, actor=actor)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_audit(db, action="connection.overdue_invoice_sync", actor_type="user", actor_id=str(actor.id), tenant_id=ctx.tenant.id, resource_type="connection", resource_id=str(conn.id), metadata={"company_id": conn.odoo_company_id, "created": created})
    return {"created": created}


@router.delete(
    "/connections/{connection_id}",
    response_model=ConnectionOut,
    dependencies=[Depends(require_csrf)],
)
def disable_connection(
    connection_id: uuid.UUID,
    ctx: TenantContext = Depends(require_role(*_WRITE_ROLES)),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    """Soft disable — the record and its encrypted credential are retained."""
    conn = _scoped_get(db, ctx, connection_id)
    conn.status = "disabled"
    conn.is_active = False
    conn.updated_by_user_id = actor.id
    record_audit(
        db,
        action="connection.disabled",
        actor_type="user",
        actor_id=str(actor.id),
        tenant_id=ctx.tenant.id,
        resource_type="connection",
        resource_id=str(conn.id),
        metadata={"provider": conn.provider, "name": conn.name},
    )
    db.flush()
    return _to_out(conn)

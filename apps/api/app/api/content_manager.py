"""Authenticated, tenant-bound Content Manager endpoint."""

import time
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.csrf import require_csrf
from app.api.deps import (
    TenantContext,
    get_current_tenant,
    get_current_user,
    get_db,
    get_tenant_id,
    require_internal_auth,
)
from app.content_manager.export import ExportFormat, build_export, safe_export_filename
from app.content_manager.provider import (
    ContentManagerProvider,
    OpenAICompatibleProvider,
    ProviderFailureError,
    ProviderUnavailableError,
)
from app.content_manager.workflow import ContentManagerWorkflow, UIConfig
from app.models import ContentDocument, ContentDocumentRevision, User
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1/agents/content-manager", tags=["content-manager"])


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


FieldValue = str | int | float | bool | None


class ContentManagerRequest(BaseModel):
    """Bounded request contract; tenant identity is deliberately absent."""

    model_config = ConfigDict(extra="forbid", strict=True)
    document_id: uuid.UUID | None = None
    original_request: str = Field(min_length=1, max_length=8000)
    provided_fields: dict[str, FieldValue] = Field(default_factory=dict, max_length=32)
    current_document: str | None = Field(default=None, max_length=30000)
    active_document_type: str | None = Field(default=None, max_length=128)
    latest_correction: str | None = Field(default=None, max_length=8000)
    conversation_messages: list[ConversationMessage] = Field(default_factory=list, max_length=30)

    @field_validator("document_id", mode="before")
    @classmethod
    def parse_document_id(cls, value: object) -> object:
        if value is None or isinstance(value, uuid.UUID):
            return value
        if isinstance(value, str):
            try:
                return uuid.UUID(value)
            except ValueError as exc:
                raise ValueError("document_id must be a UUID") from exc
        return value

    @field_validator("provided_fields")
    @classmethod
    def validate_fields(cls, value: dict[str, FieldValue]) -> dict[str, FieldValue]:
        for key, field_value in value.items():
            if not key or len(key) > 64:
                raise ValueError("provided_fields keys must be 1 to 64 characters")
            if isinstance(field_value, str) and len(field_value) > 2000:
                raise ValueError("provided_fields string values must be at most 2000 characters")
        return value


class ContentManagerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: uuid.UUID | None = None
    status: Literal["complete", "needs_information", "out_of_scope"]
    document: str | None = None
    ui: UIConfig | None = None
    document_type: str | None = None
    document_action: Literal["revise_active_document", "create_new_document"] | None = None
    redirect_message: str | None = None

class ContentManagerExportRequest(BaseModel):
    """Only reviewed text and its display type are accepted for export."""

    model_config = ConfigDict(extra="forbid", strict=True)
    document: str = Field(min_length=1, max_length=30000)
    document_type: str | None = Field(default=None, max_length=128)


class ContentDocumentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    document_type: str | None
    status: str
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    revision_count: int


class ContentDocumentRevisionResponse(BaseModel):
    id: uuid.UUID
    revision_number: int
    request_text: str
    provided_fields: dict[str, FieldValue] | None
    conversation_messages: list[ConversationMessage]
    ui: UIConfig | None
    document: str | None
    document_type: str | None
    document_action: str | None
    response_status: str
    created_by_user_id: uuid.UUID | None
    created_at: datetime


class ContentDocumentDetailResponse(BaseModel):
    id: uuid.UUID
    original_request: str
    current_document: str | None
    document_type: str | None
    latest_correction: str | None
    status: str
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    conversation_messages: list[ConversationMessage]
    ui: UIConfig | None
    revisions: list[ContentDocumentRevisionResponse]


class ContentDocumentListResponse(BaseModel):
    items: list[ContentDocumentListItem]
    total: int


def get_content_manager_provider() -> ContentManagerProvider | None:
    """Dependency seam for tests; production credentials are env-only."""
    try:
        return OpenAICompatibleProvider.from_environment()
    except ProviderUnavailableError:
        return None


def _duration_bucket(elapsed: float) -> str:
    if elapsed < 1:
        return "lt_1s"
    if elapsed < 5:
        return "1_to_5s"
    if elapsed < 30:
        return "5_to_30s"
    return "gte_30s"


def _ensure_tenant_context(
    tenant_context: TenantContext, proxy_tenant_id: uuid.UUID
) -> uuid.UUID:
    if tenant_context.tenant.id != proxy_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant context mismatch")
    return tenant_context.tenant.id


def _document_title(original_request: str) -> str:
    title = original_request.strip().splitlines()[0].strip()
    return title[:120] or "Untitled document"


def _get_document(
    db: Session, document_id: uuid.UUID, tenant_id: uuid.UUID
) -> ContentDocument | None:
    return (
        db.query(ContentDocument)
        .filter(
            ContentDocument.id == document_id,
            ContentDocument.tenant_id == tenant_id,
        )
        .one_or_none()
    )


def _serialize_messages(messages: list[ConversationMessage]) -> list[dict[str, str]]:
    return [message.model_dump() for message in messages]


def _save_document_response(
    db: Session,
    *,
    body: ContentManagerRequest,
    response: ContentManagerResponse,
    user: User,
    tenant_id: uuid.UUID,
) -> ContentDocument:
    document = (
        _get_document(db, body.document_id, tenant_id) if body.document_id is not None else None
    )
    if body.document_id is not None and document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    is_new = document is None
    if document is None:
        document = ContentDocument(
            tenant_id=tenant_id,
            created_by_user_id=user.id,
            updated_by_user_id=user.id,
            original_request=body.original_request,
            status="draft",
        )
        db.add(document)
        db.flush()
    else:
        document.updated_by_user_id = user.id

    if response.document is not None:
        document.current_document = response.document
    if response.document_type is not None:
        document.document_type = response.document_type
    if body.latest_correction is not None:
        document.latest_correction = body.latest_correction
    document.status = "complete" if response.status == "complete" else "draft"
    document.updated_at = document.updated_at or document.created_at

    next_number = (
        db.query(func.coalesce(func.max(ContentDocumentRevision.revision_number), 0))
        .filter(
            ContentDocumentRevision.document_id == document.id,
            ContentDocumentRevision.tenant_id == tenant_id,
        )
        .scalar()
        or 0
    ) + 1
    revision = ContentDocumentRevision(
        document_id=document.id,
        tenant_id=tenant_id,
        created_by_user_id=user.id,
        revision_number=next_number,
        request_text=body.latest_correction or body.original_request,
        provided_fields=body.provided_fields or None,
        conversation_messages=_serialize_messages(body.conversation_messages),
        ui_config=response.ui.model_dump() if response.ui is not None else None,
        document=response.document,
        document_type=response.document_type,
        document_action=response.document_action,
        response_status=response.status,
    )
    db.add(revision)
    record_audit(
        db,
        action="content_manager.document_created" if is_new else "content_manager.document_updated",
        actor_type="user",
        actor_id=str(user.id),
        tenant_id=tenant_id,
        resource_type="content_document",
        resource_id=str(document.id),
        metadata={
            "status": response.status,
            "revision_number": next_number,
        },
    )
    return document


def _detail_response(
    document: ContentDocument, revisions: list[ContentDocumentRevision]
) -> ContentDocumentDetailResponse:
    latest_messages = revisions[-1].conversation_messages if revisions else []
    return ContentDocumentDetailResponse(
        id=document.id,
        original_request=document.original_request,
        current_document=document.current_document,
        document_type=document.document_type,
        latest_correction=document.latest_correction,
        status=document.status,
        created_by_user_id=document.created_by_user_id,
        created_at=document.created_at,
        updated_at=document.updated_at,
        conversation_messages=[
            ConversationMessage.model_validate(message) for message in (latest_messages or [])
        ],
        ui=UIConfig.model_validate(revisions[-1].ui_config)
        if revisions and revisions[-1].ui_config
        else None,
        revisions=[
            ContentDocumentRevisionResponse(
                id=revision.id,
                revision_number=revision.revision_number,
                request_text=revision.request_text,
                provided_fields=revision.provided_fields,
                conversation_messages=[
                    ConversationMessage.model_validate(message)
                    for message in (revision.conversation_messages or [])
                ],
                ui=UIConfig.model_validate(revision.ui_config)
                if revision.ui_config
                else None,
                document=revision.document,
                document_type=revision.document_type,
                document_action=revision.document_action,
                response_status=revision.response_status,
                created_by_user_id=revision.created_by_user_id,
                created_at=revision.created_at,
            )
            for revision in revisions
        ],
    )


@router.get("/documents", response_model=ContentDocumentListResponse)
def list_documents(
    db: Annotated[Session, Depends(get_db)],
    tenant_context: Annotated[TenantContext, Depends(get_current_tenant)],
    proxy_tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    _internal_auth: Annotated[None, Depends(require_internal_auth)],
) -> ContentDocumentListResponse:
    tenant_id = _ensure_tenant_context(tenant_context, proxy_tenant_id)
    documents = (
        db.query(ContentDocument)
        .filter(ContentDocument.tenant_id == tenant_id)
        .order_by(ContentDocument.updated_at.desc(), ContentDocument.created_at.desc())
        .all()
    )
    counts = dict(
        db.query(
            ContentDocumentRevision.document_id,
            func.count(ContentDocumentRevision.id),
        )
        .filter(ContentDocumentRevision.tenant_id == tenant_id)
        .group_by(ContentDocumentRevision.document_id)
        .all()
    )
    return ContentDocumentListResponse(
        items=[
            ContentDocumentListItem(
                id=document.id,
                title=_document_title(document.original_request),
                document_type=document.document_type,
                status=document.status,
                created_by_user_id=document.created_by_user_id,
                created_at=document.created_at,
                updated_at=document.updated_at,
                revision_count=counts.get(document.id, 0),
            )
            for document in documents
        ],
        total=len(documents),
    )


@router.get("/documents/{document_id}", response_model=ContentDocumentDetailResponse)
def get_document(
    document_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    tenant_context: Annotated[TenantContext, Depends(get_current_tenant)],
    proxy_tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    _internal_auth: Annotated[None, Depends(require_internal_auth)],
) -> ContentDocumentDetailResponse:
    tenant_id = _ensure_tenant_context(tenant_context, proxy_tenant_id)
    document = _get_document(db, document_id, tenant_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    revisions = (
        db.query(ContentDocumentRevision)
        .filter(
            ContentDocumentRevision.document_id == document.id,
            ContentDocumentRevision.tenant_id == tenant_id,
        )
        .order_by(ContentDocumentRevision.revision_number.asc())
        .all()
    )
    return _detail_response(document, revisions)


@router.post("/documents", response_model=ContentManagerResponse)
def create_document(
    body: ContentManagerRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    tenant_context: Annotated[TenantContext, Depends(get_current_tenant)],
    proxy_tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    _internal_auth: Annotated[None, Depends(require_internal_auth)],
    _csrf: Annotated[None, Depends(require_csrf)],
    provider: Annotated[ContentManagerProvider | None, Depends(get_content_manager_provider)],
) -> ContentManagerResponse:
    """Generate and persist a tenant-scoped draft or revision."""
    tenant_id = _ensure_tenant_context(tenant_context, proxy_tenant_id)
    if body.document_id is not None and _get_document(db, body.document_id, tenant_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    started = time.monotonic()
    if provider is None:
        record_audit(
            db,
            action="content_manager.document_failed",
            actor_type="user",
            actor_id=str(user.id),
            tenant_id=tenant_id,
            resource_type="content_manager",
            metadata={"status": "failed", "error_category": "provider_unavailable"},
        )
        raise HTTPException(status_code=503, detail="Content Manager is temporarily unavailable")
    try:
        provider_request = body.model_dump(exclude={"document_id"})
        result = ContentManagerWorkflow(provider).execute(provider_request)
    except ProviderUnavailableError:
        record_audit(
            db,
            action="content_manager.document_failed",
            actor_type="user",
            actor_id=str(user.id),
            tenant_id=tenant_id,
            resource_type="content_manager",
            metadata={"status": "failed", "error_category": "provider_unavailable"},
        )
        raise HTTPException(status_code=503, detail="Content Manager is temporarily unavailable")
    except ProviderFailureError:
        record_audit(
            db,
            action="content_manager.document_failed",
            actor_type="user",
            actor_id=str(user.id),
            tenant_id=tenant_id,
            resource_type="content_manager",
            metadata={
                "status": "failed",
                "error_category": "provider_failure",
                "duration_bucket": _duration_bucket(time.monotonic() - started),
            },
        )
        raise HTTPException(status_code=502, detail="Content Manager provider failed")

    response = ContentManagerResponse.model_validate(result)
    document = _save_document_response(
        db,
        body=body,
        response=response,
        user=user,
        tenant_id=tenant_id,
    )
    response.document_id = document.id
    return response

@router.post("/documents/export/{file_format}")
def export_document(
    file_format: ExportFormat,
    body: ContentManagerExportRequest,
    _user: Annotated[User, Depends(get_current_user)],
    tenant_context: Annotated[TenantContext, Depends(get_current_tenant)],
    proxy_tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    _internal_auth: Annotated[None, Depends(require_internal_auth)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> Response:
    """Export the reviewed browser text without persisting or enriching it."""
    if tenant_context.tenant.id != proxy_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant context mismatch")

    try:
        content, media_type = build_export(body.document, file_format)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document export is temporarily unavailable",
        ) from exc

    filename = safe_export_filename(body.document_type, file_format)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )

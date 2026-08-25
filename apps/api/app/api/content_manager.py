"""Authenticated, tenant-bound Content Manager endpoint."""

import time
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
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
from app.content_manager.provider import (
    ContentManagerProvider,
    OpenAICompatibleProvider,
    ProviderFailureError,
    ProviderUnavailableError,
)
from app.content_manager.workflow import ContentManagerWorkflow, UIConfig
from app.models import User
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
    original_request: str = Field(min_length=1, max_length=8000)
    provided_fields: dict[str, FieldValue] = Field(default_factory=dict, max_length=32)
    current_document: str | None = Field(default=None, max_length=30000)
    active_document_type: str | None = Field(default=None, max_length=128)
    latest_correction: str | None = Field(default=None, max_length=8000)
    conversation_messages: list[ConversationMessage] = Field(default_factory=list, max_length=30)

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
    status: Literal["complete", "needs_information", "out_of_scope"]
    document: str | None = None
    ui: UIConfig | None = None
    document_type: str | None = None
    document_action: Literal["revise_active_document", "create_new_document"] | None = None
    redirect_message: str | None = None


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
    """Generate a draft without accessing Odoo or persisting user content."""
    if tenant_context.tenant.id != proxy_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant context mismatch")

    started = time.monotonic()
    if provider is None:
        record_audit(
            db,
            action="content_manager.document_failed",
            actor_type="user",
            actor_id=str(user.id),
            tenant_id=tenant_context.tenant.id,
            resource_type="content_manager",
            metadata={"status": "failed", "error_category": "provider_unavailable"},
        )
        raise HTTPException(status_code=503, detail="Content Manager is temporarily unavailable")
    try:
        result = ContentManagerWorkflow(provider).execute(body.model_dump())
    except ProviderUnavailableError:
        record_audit(
            db,
            action="content_manager.document_failed",
            actor_type="user",
            actor_id=str(user.id),
            tenant_id=tenant_context.tenant.id,
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
            tenant_id=tenant_context.tenant.id,
            resource_type="content_manager",
            metadata={
                "status": "failed",
                "error_category": "provider_failure",
                "duration_bucket": _duration_bucket(time.monotonic() - started),
            },
        )
        raise HTTPException(status_code=502, detail="Content Manager provider failed")

    response = ContentManagerResponse.model_validate(result)
    record_audit(
        db,
        action="content_manager.document_created",
        actor_type="user",
        actor_id=str(user.id),
        tenant_id=tenant_context.tenant.id,
        resource_type="content_manager",
        metadata={
            "status": response.status,
            "document_type": response.document_type or "unknown",
            "duration_bucket": _duration_bucket(time.monotonic() - started),
        },
    )
    return response

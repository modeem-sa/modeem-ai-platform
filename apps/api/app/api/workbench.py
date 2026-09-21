"""Employee-only AI workbench bound to one service request and tenant."""

import json
import uuid
from hashlib import sha256
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.csrf import require_csrf
from app.api.deps import get_current_user, get_db
from app.api.service_requests import _request_for_user
from app.content_manager.provider import (
    OpenAICompatibleProvider,
    ProviderFailureError,
    ProviderUnavailableError,
)
from app.models import AgentMessage, AgentSession, Connection, ServiceRequest, User
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1/service-requests", tags=["request-workbench"])
PROMPT_VERSION = "request-workbench-v1"
PROMPT_PATH = Path(__file__).parents[1] / "prompts" / "operations" / "request_workbench.md"
MAX_TEXT = 1200
MAX_CONTEXT_TURNS = 8
MAX_CONTEXT_CHARS = 6000


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    request_summary: str = Field(min_length=1, max_length=1200)
    customer_goal: str = Field(min_length=1, max_length=800)
    service_category: str = Field(min_length=1, max_length=120)
    required_information: list[str] = Field(max_length=10)
    missing_information: list[str] = Field(max_length=10)
    suggested_steps: list[str] = Field(max_length=10)
    potential_risks: list[str] = Field(max_length=10)
    data_sources_needed: list[str] = Field(max_length=10)
    approval_likely_required: bool


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    locale: Literal["ar", "en"] = "ar"


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    content: str = Field(min_length=1, max_length=4000)
    locale: Literal["ar", "en"] = "ar"


def _safe_text(value: str, limit: int = MAX_TEXT) -> str:
    return " ".join(value.split())[:limit]


def _connection_for_request(db: Session, request: ServiceRequest) -> Connection:
    connection = (
        db.query(Connection)
        .filter(
            Connection.tenant_id == request.tenant_id,
            Connection.provider == "odoo",
            Connection.is_active.is_(True),
            Connection.status == "configured",
            Connection.last_test_status == "success",
            Connection.selected_transport.in_(("xmlrpc", "json2")),
        )
        .order_by(Connection.last_tested_at.desc(), Connection.created_at.desc())
        .first()
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail="No active tested Odoo connection is available for this customer.",
        )
    return connection


def _session_out(db: Session, session: AgentSession | None) -> dict:
    if session is None:
        return {"session": None, "messages": []}
    messages = (
        db.query(AgentMessage)
        .filter(AgentMessage.session_id == session.id, AgentMessage.tenant_id == session.tenant_id)
        .order_by(AgentMessage.created_at, AgentMessage.id)
        .all()
    )
    return {
        "session": {
            "id": str(session.id),
            "request_id": str(session.service_request_id),
            "tenant_id": str(session.tenant_id),
            "employee_user_id": str(session.employee_user_id),
            "status": session.status,
            "provider_model": session.provider_model,
            "prompt_version": session.prompt_version,
            "analysis": json.loads(session.latest_analysis_json)
            if session.latest_analysis_json
            else None,
            "last_error": session.last_error,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        },
        "messages": [
            {
                "id": str(item.id),
                "role": item.role,
                "content": item.content,
                "analysis": json.loads(item.analysis_json) if item.analysis_json else None,
                "created_at": item.created_at,
            }
            for item in messages
        ],
    }


def _authorized_request(
    db: Session, actor: User, request_id: uuid.UUID
) -> tuple[ServiceRequest, object]:
    # _request_for_user derives tenant and request scope from the request ID.
    # It intentionally returns 404 for customers and cross-tenant users.
    return _request_for_user(db, actor, request_id, require_worker=True)


def _get_session(db: Session, request: ServiceRequest, actor: User) -> AgentSession | None:
    return (
        db.query(AgentSession)
        .filter(
            AgentSession.service_request_id == request.id,
            AgentSession.tenant_id == request.tenant_id,
            AgentSession.employee_user_id == actor.id,
        )
        .order_by(AgentSession.updated_at.desc())
        .first()
    )


def _ensure_session(db: Session, request: ServiceRequest, actor: User) -> tuple[AgentSession, Connection]:
    connection = _connection_for_request(db, request)
    session = _get_session(db, request, actor)
    if session is None:
        session = AgentSession(
            tenant_id=request.tenant_id,
            service_request_id=request.id,
            employee_user_id=actor.id,
            connection_id=connection.id,
            status="active",
            prompt_version=PROMPT_VERSION,
        )
        db.add(session)
        try:
            db.flush()
        except IntegrityError:
            # A concurrent start may win the unique request/employee slot.
            # Roll back only this attempted insert, then safely resume the
            # already-persisted session instead of creating a duplicate.
            db.rollback()
            session = _get_session(db, request, actor)
            if session is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Could not safely resume the request workbench session.",
                )
            session.connection_id = connection.id
            session.status = "active"
            session.last_error = None
            return session, connection
        record_audit(
            db,
            action="agent_session_created",
            actor_type="user",
            actor_id=str(actor.id),
            tenant_id=request.tenant_id,
            resource_type="agent_session",
            resource_id=str(session.id),
            metadata={"service_request_id": str(request.id), "connection_id": str(connection.id)},
        )
    else:
        session.connection_id = connection.id
        session.status = "active"
        session.last_error = None
    return session, connection


def _analysis_payload(request: ServiceRequest, connection: Connection, locale: str) -> dict:
    # Only non-secret connection metadata is included; encrypted credentials
    # and database authentication material never enter the provider payload.
    return {
        "response_language": "Arabic" if locale == "ar" else "English",
        "request": {
            "subject": _safe_text(request.subject, 255),
            "description": _safe_text(request.description, 4000),
            "requested_module": request.requested_module,
            "priority": request.priority,
            "status": request.status,
        },
        "customer_visible_context": [],
        "odoo_context": {
            "provider": connection.provider,
            "transport": connection.selected_transport,
            "company_configured": connection.odoo_company_id is not None,
        },
    }


def _conversation_context(
    db: Session, session: AgentSession, current_message_id: uuid.UUID
) -> list[dict[str, str]]:
    rows = (
        db.query(AgentMessage)
        .filter(
            AgentMessage.session_id == session.id,
            AgentMessage.tenant_id == session.tenant_id,
            AgentMessage.id != current_message_id,
            AgentMessage.role.in_(("user", "assistant", "system")),
        )
        .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
        .limit(MAX_CONTEXT_TURNS)
        .all()
    )
    reverse_context: list[dict[str, str]] = []
    used_chars = 0
    for item in rows:
        content = _safe_text(item.content, MAX_TEXT)
        remaining = MAX_CONTEXT_CHARS - used_chars
        if remaining <= 0:
            break
        content = content[:remaining]
        if not content:
            continue
        reverse_context.append({"role": item.role, "content": content})
        used_chars += len(content)
    return list(reversed(reverse_context))


def _audit_agent_message(
    db: Session, request: ServiceRequest, actor: User, message: AgentMessage
) -> None:
    record_audit(
        db,
        action="agent_message_created",
        actor_type="user",
        actor_id=str(actor.id),
        tenant_id=request.tenant_id,
        resource_type="agent_message",
        resource_id=str(message.id),
        metadata={
            "service_request_id": str(request.id),
            "message_id": str(message.id),
            "message_role": message.role,
        },
    )


def _provider_analysis(request: ServiceRequest, connection: Connection, locale: str) -> tuple[AnalysisResult, str]:
    prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    try:
        provider = OpenAICompatibleProvider.from_environment()
        raw = provider.generate(
            system_prompt=prompt,
            user_payload=_analysis_payload(request, connection, locale),
        )
        result = AnalysisResult.model_validate(raw)
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI provider is not configured.",
        ) from exc
    except (ProviderFailureError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI provider returned an unusable response.",
        ) from exc
    return result, str(getattr(provider, "model", "unknown"))


@router.get("/{request_id}/agent/session")
def get_agent_session(
    request_id: uuid.UUID,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _ = _authorized_request(db, actor, request_id)
    return _session_out(db, _get_session(db, request, actor))


@router.post(
    "/{request_id}/agent/session",
    dependencies=[Depends(require_csrf)],
)
def start_agent_session(
    request_id: uuid.UUID,
    body: SessionInput = SessionInput(),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _ = _authorized_request(db, actor, request_id)
    session, _ = _ensure_session(db, request, actor)
    session.prompt_version = PROMPT_VERSION
    db.commit()
    return _session_out(db, session)


@router.post(
    "/{request_id}/agent/analyze",
    dependencies=[Depends(require_csrf)],
)
def analyze_request(
    request_id: uuid.UUID,
    body: SessionInput = SessionInput(),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _ = _authorized_request(db, actor, request_id)
    session, connection = _ensure_session(db, request, actor)
    record_audit(
        db,
        action="agent_analysis_started",
        actor_type="user",
        actor_id=str(actor.id),
        tenant_id=request.tenant_id,
        resource_type="service_request",
        resource_id=str(request.id),
        metadata={"agent_session_id": str(session.id)},
    )
    try:
        result, model = _provider_analysis(request, connection, body.locale)
    except HTTPException as exc:
        session.status = "failed"
        session.last_error = str(exc.detail)
        record_audit(
            db,
            action="agent_provider_failed",
            actor_type="user",
            actor_id=str(actor.id),
            tenant_id=request.tenant_id,
            resource_type="agent_session",
            resource_id=str(session.id),
            metadata={"service_request_id": str(request.id), "status_code": exc.status_code},
        )
        db.commit()
        raise
    payload = result.model_dump()
    session.status = "active"
    session.provider_model = model
    session.prompt_version = PROMPT_VERSION
    session.prompt_sha256 = sha256(PROMPT_PATH.read_bytes()).hexdigest()
    session.latest_analysis_json = json.dumps(payload, ensure_ascii=False)
    session.last_error = None
    message = AgentMessage(
        session_id=session.id,
        tenant_id=request.tenant_id,
        role="assistant",
        content=result.request_summary,
        analysis_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(message)
    db.flush()
    _audit_agent_message(db, request, actor, message)
    record_audit(
        db,
        action="agent_analysis_completed",
        actor_type="user",
        actor_id=str(actor.id),
        tenant_id=request.tenant_id,
        resource_type="agent_session",
        resource_id=str(session.id),
        metadata={"service_request_id": str(request.id)},
    )
    db.commit()
    return _session_out(db, session)


@router.get("/{request_id}/agent/messages")
def get_agent_messages(
    request_id: uuid.UUID,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _ = _authorized_request(db, actor, request_id)
    return _session_out(db, _get_session(db, request, actor))


@router.post(
    "/{request_id}/agent/messages",
    dependencies=[Depends(require_csrf)],
)
def post_agent_message(
    request_id: uuid.UUID,
    body: MessageInput,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _ = _authorized_request(db, actor, request_id)
    session, connection = _ensure_session(db, request, actor)
    user_message = AgentMessage(
        session_id=session.id,
        tenant_id=request.tenant_id,
        role="user",
        content=_safe_text(body.content, 4000),
    )
    db.add(user_message)
    db.flush()
    _audit_agent_message(db, request, actor, user_message)
    prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    payload = _analysis_payload(request, connection, body.locale)
    payload["conversation"] = _conversation_context(db, session, user_message.id)
    payload["employee_instruction"] = _safe_text(body.content, 4000)
    try:
        provider = OpenAICompatibleProvider.from_environment()
        raw = provider.generate(
            system_prompt=prompt,
            user_payload=payload,
        )
        result = AnalysisResult.model_validate(raw)
    except ProviderUnavailableError as exc:
        session.status = "failed"
        session.last_error = "AI provider is not configured."
        record_audit(
            db,
            action="agent_provider_failed",
            actor_type="user",
            actor_id=str(actor.id),
            tenant_id=request.tenant_id,
            resource_type="agent_session",
            resource_id=str(session.id),
            metadata={"service_request_id": str(request.id), "status_code": 503},
        )
        db.commit()
        raise HTTPException(status_code=503, detail=session.last_error) from exc
    except (ProviderFailureError, ValueError, TypeError) as exc:
        session.status = "failed"
        session.last_error = "AI provider returned an unusable response."
        record_audit(
            db,
            action="agent_provider_failed",
            actor_type="user",
            actor_id=str(actor.id),
            tenant_id=request.tenant_id,
            resource_type="agent_session",
            resource_id=str(session.id),
            metadata={"service_request_id": str(request.id), "status_code": 502},
        )
        db.commit()
        raise HTTPException(status_code=502, detail=session.last_error) from exc
    response_payload = result.model_dump()
    assistant_message = AgentMessage(
        session_id=session.id,
        tenant_id=request.tenant_id,
        role="assistant",
        content=result.request_summary,
        analysis_json=json.dumps(response_payload, ensure_ascii=False),
    )
    db.add(assistant_message)
    db.flush()
    _audit_agent_message(db, request, actor, assistant_message)
    session.status = "active"
    session.provider_model = str(getattr(provider, "model", "unknown"))
    session.last_error = None
    db.commit()
    return _session_out(db, session)
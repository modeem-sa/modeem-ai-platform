"""Employee-only AI workbench bound to one service request and tenant."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.csrf import require_csrf
from app.api.deps import get_current_user, get_db
from app.api.operations import _operations_read_page
from app.api.service_requests import _request_for_user
from app.content_manager.provider import (
    OpenAICompatibleProvider,
    ProviderFailureError,
    ProviderUnavailableError,
)
from app.models import (
    AgentMessage,
    AgentSession,
    AgentToolCall,
    Connection,
    OperationAction,
    OperationActionExecutionItem,
    OperationTask,
    ServiceRequest,
    TenantMembership,
    User,
)
from app.operations.workbench_actions import (
    ACTION_REGISTRY,
    APPROVAL_POLICY,
    COLLECTION_FOLLOWUP_KEY,
    CollectionProposal,
    PrepareActionInput,
    TransitionActionInput,
    UpdateActionInput,
    _action_out,
    _audit,
    _history,
    canonical_collection_proposal,
    prepare_collection_followup,
)
from app.operations.workbench_collection_message import (
    EditWorkbenchCommunicationInput,
    PrepareWorkbenchCommunicationInput,
    SubmitWorkbenchCommunicationInput,
    edit_communication,
    prepare_communications,
    submit_communication,
)
from app.operations.workbench_tools import (
    FINANCE_TOOLS,
    RECEIVABLES_TOOL_KEY,
    TOOL_KEY,
    execute_finance_tool,
    finance_tool_input_from_instruction,
    parse_finance_tool_input,
    select_finance_tool,
)
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


class ToolExecutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tool_key: Literal[
        "finance.get_overdue_customer_invoices",
        "finance.get_customer_invoices",
        "finance.get_receivables_summary",
        "finance.get_vendor_bills",
        "finance.get_recent_payments",
    ] = TOOL_KEY
    input: dict = Field(default_factory=dict)
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
            Connection.encrypted_credentials.is_not(None),
            Connection.encryption_version.is_not(None),
            Connection.odoo_company_id.is_not(None),
        )
        .order_by(
            Connection.last_tested_at.desc().nullslast(),
            Connection.created_at.desc(),
            Connection.id.desc(),
        )
        .first()
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail="No active tested Odoo connection is available for this customer.",
        )
    return connection


def _session_out(
    db: Session,
    session: AgentSession | None,
    transient_tool_results: dict[uuid.UUID, dict] | None = None,
    actor: User | None = None,
) -> dict:
    if session is None:
        return {"session": None, "messages": [], "tool_calls": [], "actions": []}
    messages = (
        db.query(AgentMessage)
        .filter(AgentMessage.session_id == session.id, AgentMessage.tenant_id == session.tenant_id)
        .order_by(AgentMessage.created_at, AgentMessage.id)
        .all()
    )
    tool_calls = (
        db.query(AgentToolCall)
        .filter(
            AgentToolCall.session_id == session.id,
            AgentToolCall.tenant_id == session.tenant_id,
            AgentToolCall.service_request_id == session.service_request_id,
        )
        .order_by(AgentToolCall.started_at, AgentToolCall.id)
        .all()
    )
    actor_role = None
    if actor is not None:
        membership = (
            db.query(TenantMembership)
            .filter(
                TenantMembership.tenant_id == session.tenant_id,
                TenantMembership.user_id == actor.id,
                TenantMembership.is_active.is_(True),
            )
            .one_or_none()
        )
        actor_role = membership.role if membership else None
    actions = [
        _action_out(task, action, actor, actor_role, db)
        for task, action in (
            db.query(OperationTask, OperationAction)
            .join(OperationAction, OperationAction.task_id == OperationTask.id)
            .filter(
                OperationTask.tenant_id == session.tenant_id,
                OperationTask.source_type == "agent_workbench",
                OperationTask.source_reference == str(session.service_request_id),
                OperationTask.source_signal == COLLECTION_FOLLOWUP_KEY,
                OperationAction.tenant_id == session.tenant_id,
            )
            .order_by(OperationTask.created_at.desc(), OperationTask.id.desc())
            .all()
        )
    ]
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
        "actions": actions,
        "tool_calls": [
            {
                "id": str(item.id),
                "tool_key": item.tool_key,
                "mode": item.mode,
                "status": item.status,
                "input": json.loads(item.safe_input_json),
                "result": (
                    transient_tool_results[item.id]
                    if transient_tool_results and item.id in transient_tool_results
                    else json.loads(item.safe_result_summary_json)
                    if item.safe_result_summary_json
                    else None
                ),
                "error_code": item.error_code,
                "started_at": item.started_at,
                "finished_at": item.finished_at,
            }
            for item in tool_calls
        ],
    }


def _action_for_request(
    db: Session, request: ServiceRequest, action_id: uuid.UUID
) -> tuple[OperationTask, OperationAction]:
    row = (
        db.query(OperationTask, OperationAction)
        .join(OperationAction, OperationAction.task_id == OperationTask.id)
        .filter(
            OperationTask.id == OperationAction.task_id,
            OperationTask.tenant_id == request.tenant_id,
            OperationTask.source_type == "agent_workbench",
            OperationTask.source_reference == str(request.id),
            OperationTask.source_signal == COLLECTION_FOLLOWUP_KEY,
            OperationAction.id == action_id,
            OperationAction.tenant_id == request.tenant_id,
            OperationAction.workflow_key == COLLECTION_FOLLOWUP_KEY,
        )
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Workbench action not found")
    return row


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


def _tool_summary(result: dict, locale: str) -> str:
    if result["result_truncated"]:
        return (
            f"تم إرجاع {result['returned_count']} فاتورة فقط. النتيجة غير مكتملة؛ "
            "ضيّق نطاق البحث قبل الاعتماد على الإجماليات."
            if locale == "ar"
            else f"Returned {result['returned_count']} invoices. The result is incomplete; "
            "narrow the request before relying on totals."
        )
    if result["tool_key"] == RECEIVABLES_TOOL_KEY:
        if not result["totals_by_currency"]:
            return (
                "لا توجد إجماليات مكتملة للذمم المدينة ضمن النطاق."
                if locale == "ar"
                else "No complete receivables totals are available for this scope."
            )
        totals = "، ".join(
            f"{item['open_receivables_total']} {item['currency']}"
            for item in result["totals_by_currency"]
        )
        return (
            f"إجمالي الذمم المدينة حسب العملة: {totals}."
            if locale == "ar"
            else f"Open receivables by currency: {totals}."
        )
    if result["tool_key"] != TOOL_KEY:
        return (
            f"تمت قراءة {result['returned_count']} سجل مالي من Odoo."
            if locale == "ar"
            else f"Read {result['returned_count']} financial records from Odoo."
        )
    if not result["totals_by_currency"]:
        return (
            "لم يتم العثور على فواتير عملاء متأخرة ضمن الحد المحدد."
            if locale == "ar"
            else "No overdue customer invoices matched the requested threshold."
        )
    totals = "، ".join(
        f"{item['outstanding_amount']} {item['currency']}"
        for item in result["totals_by_currency"]
    )
    if locale == "ar":
        return (
            f"تم العثور على {result['returned_count']} فاتورة متأخرة تخص "
            f"{result['returned_customer_count']} عميل، بإجمالي متبقٍ حسب العملة: {totals}."
        )
    return (
        f"Found {result['returned_count']} overdue invoices across "
        f"{result['returned_customer_count']} customers. Outstanding by currency: {totals}."
    )


def _execute_finance_tool(
    db: Session,
    request: ServiceRequest,
    actor: User,
    session: AgentSession,
    connection: Connection,
    tool_key: str,
    tool_input: BaseModel,
    locale: str,
) -> tuple[uuid.UUID, dict]:
    call = AgentToolCall(
        session_id=session.id,
        tenant_id=request.tenant_id,
        service_request_id=request.id,
        employee_user_id=actor.id,
        connection_id=connection.id,
        tool_key=tool_key,
        mode="read",
        status="started",
        safe_input_json=json.dumps(tool_input.model_dump(), sort_keys=True),
    )
    db.add(call)
    db.flush()
    record_audit(
        db,
        action="agent_tool_started",
        actor_type="user",
        actor_id=str(actor.id),
        tenant_id=request.tenant_id,
        resource_type="agent_tool_call",
        resource_id=str(call.id),
        metadata={
            "service_request_id": str(request.id),
            "agent_session_id": str(session.id),
            "tool_key": tool_key,
            "mode": "read",
        },
    )
    try:
        result_model = execute_finance_tool(
            db=db,
            actor=actor,
            request=request,
            connection=connection,
            tool_key=tool_key,
            tool_input=tool_input,
            read_page=_operations_read_page,
        )
    except HTTPException as exc:
        call.status = "failed"
        call.error_code = f"http_{exc.status_code}"
        call.finished_at = datetime.now(UTC)
        session.last_error = str(exc.detail)
        record_audit(
            db,
            action="agent_tool_failed",
            actor_type="user",
            actor_id=str(actor.id),
            tenant_id=request.tenant_id,
            resource_type="agent_tool_call",
            resource_id=str(call.id),
            metadata={
                "service_request_id": str(request.id),
                "agent_session_id": str(session.id),
                "tool_key": tool_key,
                "error_code": call.error_code,
            },
        )
        db.commit()
        raise
    except Exception as exc:
        call.status = "failed"
        call.error_code = "tool_execution_failed"
        call.finished_at = datetime.now(UTC)
        session.last_error = "The finance read tool failed safely."
        record_audit(
            db,
            action="agent_tool_failed",
            actor_type="user",
            actor_id=str(actor.id),
            tenant_id=request.tenant_id,
            resource_type="agent_tool_call",
            resource_id=str(call.id),
            metadata={
                "service_request_id": str(request.id),
                "agent_session_id": str(session.id),
                "tool_key": tool_key,
                "error_code": call.error_code,
            },
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The finance read tool failed safely.",
        ) from exc

    result = result_model.model_dump()
    result["connection_name"] = connection.name
    result_summary = {
        key: value
        for key, value in result.items()
        if key not in {"invoices", "bills", "payments", "filters_used"}
    }
    call.status = "completed"
    call.safe_result_summary_json = json.dumps(
        result_summary,
        ensure_ascii=False,
        sort_keys=True,
    )
    call.finished_at = datetime.now(UTC)
    assistant_message = AgentMessage(
        session_id=session.id,
        tenant_id=request.tenant_id,
        role="assistant",
        content=_tool_summary(result, locale),
    )
    db.add(assistant_message)
    db.flush()
    _audit_agent_message(db, request, actor, assistant_message)
    record_audit(
        db,
        action="agent_tool_completed",
        actor_type="user",
        actor_id=str(actor.id),
        tenant_id=request.tenant_id,
        resource_type="agent_tool_call",
        resource_id=str(call.id),
        metadata={
            "service_request_id": str(request.id),
            "agent_session_id": str(session.id),
            "tool_key": tool_key,
            "result_count": result["returned_count"],
            "result_truncated": result["result_truncated"],
        },
    )
    session.status = "active"
    session.last_error = None
    db.commit()
    return call.id, result


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
    return _session_out(db, _get_session(db, request, actor), actor=actor)


@router.get("/{request_id}/agent/actions")
def list_agent_actions(
    request_id: uuid.UUID,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, membership = _authorized_request(db, actor, request_id)
    return {
        "actions": [
            _action_out(task, action, actor, membership.role, db)
            for task, action in (
                db.query(OperationTask, OperationAction)
                .join(OperationAction, OperationAction.task_id == OperationTask.id)
                .filter(
                    OperationTask.tenant_id == request.tenant_id,
                    OperationTask.source_type == "agent_workbench",
                    OperationTask.source_reference == str(request.id),
                    OperationTask.source_signal == COLLECTION_FOLLOWUP_KEY,
                    OperationAction.tenant_id == request.tenant_id,
                )
                .order_by(OperationTask.created_at.desc(), OperationTask.id.desc())
                .all()
            )
        ]
    }


@router.get("/{request_id}/agent/actions/{action_id}/communications")
def list_workbench_communications(
    request_id: uuid.UUID,
    action_id: uuid.UUID,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _ = _authorized_request(db, actor, request_id)
    _task, action = _action_for_request(db, request, action_id)
    from app.models import WorkbenchCollectionMessage

    messages = (
        db.query(WorkbenchCollectionMessage)
        .filter_by(
            tenant_id=request.tenant_id,
            service_request_id=request.id,
            action_id=action.id,
        )
        .order_by(WorkbenchCollectionMessage.partner_id, WorkbenchCollectionMessage.id)
        .all()
    )
    from app.operations.workbench_collection_message import _message_out

    return {"messages": [_message_out(message) for message in messages]}


@router.post(
    "/{request_id}/agent/actions/{action_id}/communications/prepare",
    dependencies=[Depends(require_csrf)],
)
def prepare_workbench_communications(
    request_id: uuid.UUID,
    action_id: uuid.UUID,
    body: PrepareWorkbenchCommunicationInput,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _ = _authorized_request(db, actor, request_id)
    _task, action = _action_for_request(db, request, action_id)
    return {"messages": prepare_communications(db, actor, request, action, body)}


@router.patch(
    "/{request_id}/agent/communications/{message_id}",
    dependencies=[Depends(require_csrf)],
)
def edit_workbench_communication(
    request_id: uuid.UUID,
    message_id: uuid.UUID,
    body: EditWorkbenchCommunicationInput,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _ = _authorized_request(db, actor, request_id)
    return {"message": edit_communication(db, actor, request, message_id, body)}


@router.post(
    "/{request_id}/agent/communications/{message_id}/submit",
    dependencies=[Depends(require_csrf)],
)
def submit_workbench_communication(
    request_id: uuid.UUID,
    message_id: uuid.UUID,
    body: SubmitWorkbenchCommunicationInput,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _ = _authorized_request(db, actor, request_id)
    return {"message": submit_communication(db, actor, request, message_id, body)}


@router.post(
    "/{request_id}/agent/actions/prepare",
    dependencies=[Depends(require_csrf)],
)
def prepare_agent_action(
    request_id: uuid.UUID,
    body: PrepareActionInput,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _ = _authorized_request(db, actor, request_id)
    if COLLECTION_FOLLOWUP_KEY not in ACTION_REGISTRY:
        raise HTTPException(status_code=422, detail="Unsupported Workbench action")
    session, connection = _ensure_session(db, request, actor)
    result = prepare_collection_followup(
        db=db,
        actor=actor,
        request=request,
        connection=connection,
        session=session,
        body=body,
        read_page=_operations_read_page,
    )
    return {"action": result, "session": _session_out(db, session, actor=actor)}


@router.patch(
    "/{request_id}/agent/actions/{action_id}",
    dependencies=[Depends(require_csrf)],
)
def update_agent_action(
    request_id: uuid.UUID,
    action_id: uuid.UUID,
    body: UpdateActionInput,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _ = _authorized_request(db, actor, request_id)
    task, action = _action_for_request(db, request, action_id)
    if (
        action.status != "proposed"
        or action.version != body.expected_action_version
        or action.proposal_hash != body.expected_proposal_hash
        or task.created_by_user_id != actor.id
    ):
        raise HTTPException(status_code=409, detail="Workbench action is not editable")
    proposal = CollectionProposal.model_validate(
        json.loads(action.proposal_json), strict=False
    ).model_copy(
        update={
            "draft_message": body.draft_message,
            "internal_note": body.internal_note,
            "followup_type": body.followup_type,
        }
    )
    payload, digest = canonical_collection_proposal(proposal)
    action.proposal_json = payload
    action.proposal_hash = digest
    action.version += 1
    task.decision_note = None
    _history(db, action, actor, "regenerated", "editable_fields_updated")
    _audit(db, "agent_action_updated", actor, request, str(action.id), {"changed": "editable_fields"})
    db.commit()
    return {"action": _action_out(task, action, actor, "member", db)}


@router.post(
    "/{request_id}/agent/actions/{action_id}/submit",
    dependencies=[Depends(require_csrf)],
)
def submit_agent_action(
    request_id: uuid.UUID,
    action_id: uuid.UUID,
    body: TransitionActionInput,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _ = _authorized_request(db, actor, request_id)
    task, action = _action_for_request(db, request, action_id)
    if (
        action.status != "proposed"
        or action.version != body.expected_action_version
        or action.proposal_hash != body.expected_proposal_hash
        or task.created_by_user_id != actor.id
    ):
        raise HTTPException(status_code=409, detail="Workbench action has been modified")
    action.status = "awaiting_approval"
    action.version += 1
    task.status = "submitted_for_approval"
    task.submitted_at = datetime.now(UTC)
    _history(db, action, actor, "submitted")
    _audit(db, "agent_action_submitted_for_approval", actor, request, str(action.id))
    db.commit()
    return {"action": _action_out(task, action, actor, "member", db)}


@router.post(
    "/{request_id}/agent/actions/{action_id}/approve",
    dependencies=[Depends(require_csrf)],
)
def approve_agent_action(
    request_id: uuid.UUID,
    action_id: uuid.UUID,
    body: TransitionActionInput,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, membership = _authorized_request(db, actor, request_id)
    task, action = _action_for_request(db, request, action_id)
    if membership.role not in {"owner", "admin", "manager"}:
        raise HTTPException(status_code=403, detail="Manager approval is required")
    if task.created_by_user_id == actor.id:
        raise HTTPException(status_code=403, detail="The preparer cannot approve this action")
    if (
        action.status != "awaiting_approval"
        or action.version != body.expected_action_version
        or action.proposal_hash != body.expected_proposal_hash
    ):
        raise HTTPException(status_code=409, detail="Workbench action has been modified")
    _current_payload, current_hash = canonical_collection_proposal(
        CollectionProposal.model_validate(json.loads(action.proposal_json), strict=False)
    )
    if current_hash != action.proposal_hash:
        raise HTTPException(status_code=409, detail="Approval hash is invalid")
    action.status = "approved"
    action.approved_hash = current_hash
    action.approved_by_user_id = actor.id
    action.approved_at = datetime.now(UTC)
    action.version += 1
    task.status = "approved"
    task.decided_at = datetime.now(UTC)
    task.decision_note = None
    _history(db, action, actor, "approved")
    _audit(db, "agent_action_approved", actor, request, str(action.id), {"approval_policy": APPROVAL_POLICY})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Action changed concurrently") from exc
    return {"action": _action_out(task, action, actor, membership.role, db)}


@router.post(
    "/{request_id}/agent/actions/{action_id}/reject",
    dependencies=[Depends(require_csrf)],
)
def reject_agent_action(
    request_id: uuid.UUID,
    action_id: uuid.UUID,
    body: TransitionActionInput,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, membership = _authorized_request(db, actor, request_id)
    task, action = _action_for_request(db, request, action_id)
    if membership.role not in {"owner", "admin", "manager"}:
        raise HTTPException(status_code=403, detail="Manager approval is required")
    if task.created_by_user_id == actor.id:
        raise HTTPException(status_code=403, detail="The preparer cannot reject this action")
    if (
        action.status != "awaiting_approval"
        or action.version != body.expected_action_version
        or action.proposal_hash != body.expected_proposal_hash
    ):
        raise HTTPException(status_code=409, detail="Workbench action has been modified")
    action.status = "proposed"
    action.approved_hash = action.approved_by_user_id = action.approved_at = None
    action.version += 1
    task.status = "rejected"
    task.decided_at = datetime.now(UTC)
    task.decision_note = "Rejected: " + (body.rejection_reason or "No reason provided.")
    _history(db, action, actor, "rejected", "manager_rejected")
    _audit(db, "agent_action_rejected", actor, request, str(action.id))
    db.commit()
    return {"action": _action_out(task, action, actor, membership.role, db)}


@router.post(
    "/{request_id}/agent/actions/{action_id}/queue",
    dependencies=[Depends(require_csrf)],
)
def queue_agent_action(
    request_id: uuid.UUID,
    action_id: uuid.UUID,
    body: TransitionActionInput,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, membership = _authorized_request(db, actor, request_id)
    task, action = _action_for_request(db, request, action_id)
    if membership.role not in {"owner", "admin", "manager"}:
        raise HTTPException(status_code=403, detail="Manager queueing is required")
    if (
        action.status != "approved"
        or action.version != body.expected_action_version
        or action.proposal_hash != body.expected_proposal_hash
        or action.approved_by_user_id is None
        or action.approved_at is None
        or action.workflow_key != COLLECTION_FOLLOWUP_KEY
        or action.workflow_config_version != 1
    ):
        raise HTTPException(status_code=409, detail="Action is not approved")
    proposal = CollectionProposal.model_validate(json.loads(action.proposal_json), strict=False)
    payload, digest = canonical_collection_proposal(proposal)
    if (
        payload != action.proposal_json
        or digest != action.proposal_hash
        or action.approved_hash != digest
        or proposal.service_request_id != request.id
        or proposal.tenant_id != request.tenant_id
        or proposal.connection_id != task.source_connection_id
        or proposal.company_id <= 0
        or task.source_type != "agent_workbench"
        or task.source_signal != COLLECTION_FOLLOWUP_KEY
        or task.source_reference != str(request.id)
    ):
        raise HTTPException(status_code=409, detail="Approved action identity is invalid")
    connection = (
        db.query(Connection)
        .filter(
            Connection.id == proposal.connection_id,
            Connection.tenant_id == request.tenant_id,
            Connection.provider == "odoo",
            Connection.is_active.is_(True),
            Connection.status == "configured",
            Connection.last_test_status == "success",
            Connection.selected_transport.in_(("xmlrpc", "json2")),
            Connection.encrypted_credentials.is_not(None),
            Connection.encryption_version.is_not(None),
            Connection.odoo_company_id == proposal.company_id,
        )
        .one_or_none()
    )
    if connection is None:
        raise HTTPException(status_code=409, detail="Approved action connection is unavailable")
    existing = db.query(OperationActionExecutionItem).filter_by(action_id=action.id).count()
    if existing:
        raise HTTPException(status_code=409, detail="Action has already been queued")
    for target in proposal.target_records:
        marker = sha256(
            f"{action.id}:{target['invoice_id']}:internal_invoice_activity_v1".encode()
        ).hexdigest()
        db.add(OperationActionExecutionItem(
            action_id=action.id,
            task_id=task.id,
            tenant_id=request.tenant_id,
            invoice_id=target["invoice_id"],
            idempotency_marker=marker,
        ))
    action.execution_deadline = (
        datetime.now(UTC).date() + timedelta(days=7)
    ).isoformat()
    action.execution_policy_id = "internal_invoice_activity_v1"
    action.status = "queued"
    action.version += 1
    _history(db, action, actor, "queued", "internal_invoice_activity_v1")
    _audit(
        db, "agent_action_queued", actor, request, str(action.id),
        {"policy_id": action.execution_policy_id},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Action has already been queued") from exc
    return {"action": _action_out(task, action, actor, membership.role, db)}


@router.post(
    "/{request_id}/agent/actions/{action_id}/retry",
    dependencies=[Depends(require_csrf)],
)
def retry_agent_action(
    request_id: uuid.UUID,
    action_id: uuid.UUID,
    body: TransitionActionInput,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, membership = _authorized_request(db, actor, request_id)
    task, action = _action_for_request(db, request, action_id)
    if membership.role not in {"owner", "admin", "manager"}:
        raise HTTPException(status_code=403, detail="Manager retry is required")
    proposal = CollectionProposal.model_validate(json.loads(action.proposal_json), strict=False)
    _, digest = canonical_collection_proposal(proposal)
    if (
        action.status != "failed" or action.version != body.expected_action_version
        or action.proposal_hash != body.expected_proposal_hash
        or digest != action.proposal_hash or action.approved_hash != digest
        or action.approved_by_user_id is None or action.approved_at is None
        or action.workflow_key != COLLECTION_FOLLOWUP_KEY
        or action.workflow_config_version != 1
        or proposal.tenant_id != request.tenant_id
        or proposal.service_request_id != request.id
        or proposal.connection_id != task.source_connection_id
        or task.source_type != "agent_workbench"
        or task.source_signal != COLLECTION_FOLLOWUP_KEY
        or task.source_reference != str(request.id)
        or action.execution_policy_id != "internal_invoice_activity_v1"
        or action.execution_deadline is None
    ):
        raise HTTPException(status_code=409, detail="Action is not retryable")
    connection = (
        db.query(Connection)
        .filter(
            Connection.id == proposal.connection_id,
            Connection.tenant_id == request.tenant_id,
            Connection.provider == "odoo",
            Connection.is_active.is_(True),
            Connection.status == "configured",
            Connection.last_test_status == "success",
            Connection.selected_transport.in_(("xmlrpc", "json2")),
            Connection.encrypted_credentials.is_not(None),
            Connection.encryption_version.is_not(None),
            Connection.odoo_company_id == proposal.company_id,
        )
        .one_or_none()
    )
    if connection is None:
        raise HTTPException(status_code=409, detail="Action connection is unavailable")
    items = db.query(OperationActionExecutionItem).filter_by(action_id=action.id).all()
    if not items or any(item.attempt_count >= 3 and item.status != "succeeded" for item in items):
        raise HTTPException(status_code=409, detail="Retry limit reached")
    for item in items:
        if item.status != "succeeded":
            item.status = "pending"
            item.error = None
    action.status = "queued"
    action.error = None
    action.version += 1
    _history(db, action, actor, "retry_queued", "internal_invoice_activity_v1")
    _audit(db, "agent_action_retry_queued", actor, request, str(action.id))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Action changed concurrently") from exc
    return {"action": _action_out(task, action, actor, membership.role, db)}


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
    return _session_out(db, session, actor=actor)


@router.post(
    "/{request_id}/agent/tools/execute",
    dependencies=[Depends(require_csrf)],
)
def execute_agent_tool(
    request_id: uuid.UUID,
    body: ToolExecutionInput,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _ = _authorized_request(db, actor, request_id)
    session, connection = _ensure_session(db, request, actor)
    tool_input = parse_finance_tool_input(body.tool_key, body.input)
    call_id, result = _execute_finance_tool(
        db,
        request,
        actor,
        session,
        connection,
        body.tool_key,
        tool_input,
        body.locale,
    )
    return _session_out(db, session, {call_id: result}, actor=actor)


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
    return _session_out(db, session, actor=actor)


@router.get("/{request_id}/agent/messages")
def get_agent_messages(
    request_id: uuid.UUID,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request, _ = _authorized_request(db, actor, request_id)
    return _session_out(db, _get_session(db, request, actor), actor=actor)


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
    selected_tool = select_finance_tool(body.content)
    if selected_tool in FINANCE_TOOLS:
        call_id, result = _execute_finance_tool(
            db,
            request,
            actor,
            session,
            connection,
            selected_tool,
            finance_tool_input_from_instruction(body.content, selected_tool),
            body.locale,
        )
        return _session_out(db, session, {call_id: result}, actor=actor)
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
    return _session_out(db, session, actor=actor)
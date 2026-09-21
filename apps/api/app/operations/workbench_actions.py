"""Server-owned, non-executing actions for the request Workbench."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.models import (
    AgentSession,
    AgentToolCall,
    Connection,
    OperationAction,
    OperationActionExecutionItem,
    OperationActionHistory,
    OperationTask,
    ServiceRequest,
    TenantMembership,
    User,
)
from app.operations.workbench_tools import (
    TOOL_KEY,
    execute_overdue_customer_invoices,
    parse_finance_tool_input,
)
from app.services.audit import record_audit

COLLECTION_FOLLOWUP_KEY = "finance.prepare_collection_followup"
APPROVAL_POLICY = "internal_manager"


class ActionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    key: Literal["finance.prepare_collection_followup"]
    description: str
    mode: Literal["prepare"]
    approval_policy: Literal["internal_manager"]


ACTION_REGISTRY = {
    COLLECTION_FOLLOWUP_KEY: ActionDefinition(
        key=COLLECTION_FOLLOWUP_KEY,
        description="Prepare a reviewable collection follow-up from trusted overdue invoices.",
        mode="prepare",
        approval_policy=APPROVAL_POLICY,
    )
}


class PrepareActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_tool_call_id: str = Field(min_length=36, max_length=36)
    locale: Literal["ar", "en"] = "ar"


class UpdateActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_action_version: int = Field(ge=1)
    expected_proposal_hash: str = Field(min_length=64, max_length=64)
    draft_message: str = Field(min_length=1, max_length=2000)
    internal_note: str = Field(default="", max_length=2000)
    followup_type: Literal["phone", "email", "message", "review"] = "email"


class TransitionActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_action_version: int = Field(ge=1)
    expected_proposal_hash: str = Field(min_length=64, max_length=64)
    rejection_reason: str | None = Field(default=None, max_length=500)


class CollectionProposal(BaseModel):
    """Canonical proposal: server-bound evidence plus explicitly editable text."""

    model_config = ConfigDict(extra="forbid", strict=True)

    action_key: Literal["finance.prepare_collection_followup"]
    approval_policy: Literal["internal_manager"]
    service_request_id: uuid.UUID
    tenant_id: uuid.UUID
    connection_id: uuid.UUID
    company_id: int = Field(gt=0)
    source_tool_call_id: uuid.UUID
    requested_source_tool_call_id: uuid.UUID
    source_snapshot_hash: str = Field(min_length=64, max_length=64)
    source_as_of: str
    source_tool_input: dict[str, Any]
    target_records: list[dict[str, Any]] = Field(min_length=1, max_length=200)
    totals_by_currency: list[dict[str, Any]] = Field(max_length=50)
    followup_type: Literal["phone", "email", "message", "review"]
    draft_message: str = Field(min_length=1, max_length=2000)
    internal_note: str = Field(default="", max_length=2000)
    reverify_before_execution: Literal[True] = True


def canonical_collection_proposal(value: CollectionProposal) -> tuple[str, str]:
    payload = json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return payload, sha256(payload.encode("utf-8")).hexdigest()


def _default_message(locale: str, count: int) -> str:
    if locale == "ar":
        return (
            f"السادة/ العميل الكريم، نود التذكير بوجود {count} فاتورة مستحقة. "
            "يرجى التواصل معنا لترتيب السداد."
        )
    return (
        f"Dear customer, this is a reminder that {count} invoice(s) are overdue. "
        "Please contact us to arrange payment."
    )


def _membership(db: Session, request: ServiceRequest, actor: User) -> TenantMembership:
    membership = (
        db.query(TenantMembership)
        .filter(
            TenantMembership.tenant_id == request.tenant_id,
            TenantMembership.user_id == actor.id,
            TenantMembership.is_active.is_(True),
        )
        .one_or_none()
    )
    if membership is None or membership.role not in {"owner", "admin", "manager", "member"}:
        raise HTTPException(status_code=404, detail="Service request not found")
    return membership


def _action_query(db: Session, request: ServiceRequest) -> list[tuple[OperationTask, OperationAction]]:
    rows = (
        db.query(OperationTask, OperationAction)
        .join(OperationAction, OperationAction.task_id == OperationTask.id)
        .filter(
            OperationTask.tenant_id == request.tenant_id,
            OperationTask.source_type == "agent_workbench",
            OperationTask.source_reference == str(request.id),
            OperationTask.source_signal == COLLECTION_FOLLOWUP_KEY,
            OperationAction.tenant_id == request.tenant_id,
            OperationAction.workflow_key == COLLECTION_FOLLOWUP_KEY,
        )
        .order_by(OperationTask.created_at.desc(), OperationTask.id.desc())
        .all()
    )
    return rows


def _action_out(
    task: OperationTask, action: OperationAction, actor: User | None = None,
    actor_role: str | None = None, db: Session | None = None
) -> dict[str, Any]:
    proposal = json.loads(action.proposal_json)
    items = (
        db.query(OperationActionExecutionItem)
        .filter_by(action_id=action.id, tenant_id=action.tenant_id)
        .order_by(OperationActionExecutionItem.invoice_id)
        .all()
        if db is not None else []
    )
    verified_count = sum(
        item.status == "succeeded" and item.external_activity_id is not None
        for item in items
    )
    retryable = (
        action.status == "failed" and bool(items)
        and any(item.status != "succeeded" and item.attempt_count < 3 for item in items)
        and action.error not in {"stale_requires_reapproval", "proposal_validation_failed"}
    )
    return {
        "id": str(action.id),
        "task_id": str(task.id),
        "service_request_id": proposal["service_request_id"],
        "action_key": action.workflow_key,
        "status": action.status,
        "approval_policy": proposal["approval_policy"],
        "proposal": proposal,
        "proposal_hash": action.proposal_hash,
        "proposal_hash_short": action.proposal_hash[:12],
        "approved_hash": action.approved_hash,
        "approved_by_user_id": str(action.approved_by_user_id) if action.approved_by_user_id else None,
        "approved_at": action.approved_at,
        "prepared_by_user_id": str(task.created_by_user_id),
        "prepared_at": task.created_at,
        "updated_at": action.updated_at,
        "version": action.version,
        "rejection_reason": task.decision_note if action.status == "proposed" else None,
        "not_executed": action.status != "succeeded",
        "can_edit": bool(actor and action.status == "proposed" and task.created_by_user_id == actor.id),
        "can_submit": bool(actor and action.status == "proposed" and task.created_by_user_id == actor.id),
        "can_approve": bool(actor and action.status == "awaiting_approval"
                            and actor.id != task.created_by_user_id
                            and _is_manager_role(actor_role)),
        "can_reject": bool(actor and action.status == "awaiting_approval"
                           and actor.id != task.created_by_user_id
                           and _is_manager_role(actor_role)),
        "execution_items": [
            {
                "id": str(item.id), "invoice_id": item.invoice_id,
                "idempotency_marker": item.idempotency_marker,
                "status": item.status, "attempt_count": item.attempt_count,
                "external_activity_id": item.external_activity_id, "error": item.error,
                "receipt": json.loads(item.receipt_json) if item.receipt_json else None,
                "started_at": item.started_at, "finished_at": item.finished_at,
                "verified_at": item.verified_at,
            } for item in items
        ],
        "execution_item_count": len(items),
        "target_count": len(proposal.get("target_records", [])),
        "verified_count": verified_count,
        "last_execution_at": max(
            (item.finished_at for item in items if item.finished_at), default=None
        ),
        "can_queue_execution": bool(
            actor and action.status == "approved" and _is_manager_role(actor_role)
        ),
        "can_retry_execution": bool(
            actor and retryable and _is_manager_role(actor_role)
        ),
    }


def _is_manager_role(role: str | None) -> bool:
    return role in {"owner", "admin", "manager"}


def _audit(db: Session, action: str, actor: User, request: ServiceRequest, resource_id: str, metadata: dict[str, Any] | None = None) -> None:
    from app.services.audit import record_audit

    record_audit(
        db,
        action=action,
        actor_type="user",
        actor_id=str(actor.id),
        tenant_id=request.tenant_id,
        resource_type="agent_action",
        resource_id=resource_id,
        metadata={"service_request_id": str(request.id), **(metadata or {})},
    )


def _history(db: Session, action: OperationAction, actor: User, event_name: str, detail: str | None = None) -> None:
    db.add(
        OperationActionHistory(
            action_id=action.id,
            task_id=action.task_id,
            tenant_id=action.tenant_id,
            actor_type="user",
            actor_id=str(actor.id),
            event=event_name,
            version=action.version,
            status=action.status,
            proposal_hash=action.proposal_hash,
            detail=detail,
        )
    )


def prepare_collection_followup(
    *,
    db: Session,
    actor: User,
    request: ServiceRequest,
    connection: Connection,
    session: AgentSession,
    body: PrepareActionInput,
    read_page,
) -> dict[str, Any]:
    try:
        source_tool_call_id = uuid.UUID(body.source_tool_call_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid source tool call") from exc
    source = (
        db.query(AgentToolCall)
        .filter(
            AgentToolCall.id == source_tool_call_id,
            AgentToolCall.tenant_id == request.tenant_id,
            AgentToolCall.service_request_id == request.id,
            AgentToolCall.employee_user_id == actor.id,
            AgentToolCall.connection_id == connection.id,
            AgentToolCall.tool_key == TOOL_KEY,
            AgentToolCall.mode == "read",
            AgentToolCall.status == "completed",
        )
        .one_or_none()
    )
    if source is None:
        raise HTTPException(status_code=409, detail="A completed compatible finance read is required")
    try:
        source_input = json.loads(source.safe_input_json)
        tool_input = parse_finance_tool_input(TOOL_KEY, source_input)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail="The source finance read cannot be reused") from exc
    refreshed = AgentToolCall(
        session_id=session.id,
        tenant_id=request.tenant_id,
        service_request_id=request.id,
        employee_user_id=actor.id,
        connection_id=connection.id,
        tool_key=TOOL_KEY,
        mode="read",
        status="started",
        safe_input_json=json.dumps(source_input, sort_keys=True),
    )
    db.add(refreshed)
    db.flush()
    try:
        result = execute_overdue_customer_invoices(
            db=db,
            actor=actor,
            request=request,
            connection=connection,
            tool_input=tool_input,
            read_page=read_page,
        ).model_dump(mode="json")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        refreshed.status = "failed"
        refreshed.error_code = "refresh_failed"
        refreshed.finished_at = datetime.now(UTC)
        raise HTTPException(status_code=409, detail="The source finance read cannot be reused") from exc
    if result["result_truncated"] or not result["complete"]:
        refreshed.status = "failed"
        refreshed.error_code = "incomplete_snapshot"
        refreshed.finished_at = datetime.now(UTC)
        raise HTTPException(status_code=409, detail="Narrow the finance read before preparing a follow-up")
    if not result["invoices"]:
        refreshed.status = "completed"
        refreshed.safe_result_summary_json = json.dumps(
            {"as_of": result["as_of"], "returned_count": 0},
            sort_keys=True,
        )
        refreshed.finished_at = datetime.now(UTC)
        raise HTTPException(status_code=409, detail="No overdue invoices are available for follow-up")
    snapshot = {
        "as_of": result["as_of"],
        "target_records": [
            {
                "invoice_id": row["id"],
                "customer_id": row["customer_id"],
                "currency_id": row["currency_id"],
                "remaining_amount": row["remaining_amount"],
            }
            for row in result["invoices"]
        ],
        "totals_by_currency": result["totals_by_currency"],
    }
    snapshot_payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    snapshot_hash = sha256(snapshot_payload.encode("utf-8")).hexdigest()
    refreshed.status = "completed"
    refreshed.safe_result_summary_json = json.dumps(
        {"as_of": result["as_of"], "returned_count": result["returned_count"],
         "source_snapshot_hash": snapshot_hash, "totals_by_currency": result["totals_by_currency"]},
        ensure_ascii=False, sort_keys=True,
    )
    refreshed.finished_at = datetime.now(UTC)
    record_audit(
        db,
        action="agent_tool_refreshed",
        actor_type="user",
        actor_id=str(actor.id),
        tenant_id=request.tenant_id,
        resource_type="agent_tool_call",
        resource_id=str(refreshed.id),
        metadata={
            "service_request_id": str(request.id),
            "tool_key": TOOL_KEY,
            "source_snapshot_hash": snapshot_hash,
        },
    )
    proposal = CollectionProposal(
        action_key=COLLECTION_FOLLOWUP_KEY,
        approval_policy=APPROVAL_POLICY,
        service_request_id=request.id,
        tenant_id=request.tenant_id,
        connection_id=connection.id,
        company_id=connection.odoo_company_id or 0,
        source_tool_call_id=refreshed.id,
        requested_source_tool_call_id=source.id,
        source_snapshot_hash=snapshot_hash,
        source_as_of=result["as_of"],
        source_tool_input=source_input,
        target_records=[
            {
                "invoice_id": row["id"],
                "customer_id": row["customer_id"],
                "customer": row["customer"],
                "invoice_number": row["invoice_number"],
                "reference": row["invoice_number"],
                "due_date": row["due_date"],
                "currency_id": row["currency_id"],
                "currency": row["currency"],
                "remaining_amount": row["remaining_amount"],
                "days_overdue": row["days_overdue"],
            }
            for row in result["invoices"]
        ],
        totals_by_currency=[
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in result["totals_by_currency"]
        ],
        followup_type="email",
        draft_message=_default_message(body.locale, len(result["invoices"])),
    )
    payload, digest = canonical_collection_proposal(proposal)
    task = OperationTask(
        tenant_id=request.tenant_id,
        title="Collection follow-up",
        description="Prepared financial follow-up; approval does not execute it.",
        category="financial",
        procedure_type=COLLECTION_FOLLOWUP_KEY,
        request_data_json=json.dumps({"service_request_id": str(request.id)}, sort_keys=True),
        priority="medium",
        status="pending",
        created_by_user_id=actor.id,
        source_type="agent_workbench",
        source_connection_id=connection.id,
        source_signal=COLLECTION_FOLLOWUP_KEY,
        source_reference=str(request.id),
        source_snapshot_json=json.dumps(
            {"source_tool_call_id": str(refreshed.id), "requested_source_tool_call_id": str(source.id),
             "as_of": result["as_of"], "count": len(result["invoices"]), "source_snapshot_hash": snapshot_hash},
            sort_keys=True,
        ),
        source_synced_at=datetime.now(UTC),
        source_sync_state="read_only_snapshot",
    )
    db.add(task)
    db.flush()
    action = OperationAction(
        tenant_id=request.tenant_id,
        task_id=task.id,
        proposal_json=payload,
        proposal_hash=digest,
        idempotency_marker=uuid.uuid4().hex,
        workflow_key=COLLECTION_FOLLOWUP_KEY,
        workflow_config_version=1,
    )
    db.add(action)
    db.flush()
    _history(db, action, actor, "generated")
    _audit(db, "agent_action_prepared", actor, request, str(action.id), {"action_key": COLLECTION_FOLLOWUP_KEY, "source_snapshot_hash": snapshot_hash})
    db.commit()
    return _action_out(task, action, actor, "member", db)
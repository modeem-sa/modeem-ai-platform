"""Request-bound Phase 4C collection drafts.

This module deliberately has no delivery capability.  It only prepares,
edits, and submits customer-message drafts for a separate approval boundary.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.odoo.errors import ConnectorError
from app.integrations.odoo.invoice_chatter_collection import (
    CollectionMessagePolicyError,
    read_invoice_collection_snapshot,
)
from app.models import (
    Connection,
    OperationAction,
    OperationActionExecutionItem,
    OperationTask,
    ServiceRequest,
    User,
    WorkbenchCollectionMessage,
    WorkbenchCollectionMessageEvent,
)
from app.operations.collection_message import canonical_collection_message
from app.operations.workbench_actions import (
    COLLECTION_FOLLOWUP_KEY,
    CollectionProposal,
    canonical_collection_proposal,
)
from app.services.audit import record_audit
from app.services.connection_auth import AuthMaterialError, resolve_auth_material
from app.services.credential_crypto import (
    CredentialDecryptionError,
    EncryptionConfigError,
    decrypt_credentials,
)


class PrepareWorkbenchCommunicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    locale: str = Field(default="ar", pattern="^(ar|en)$")


class EditWorkbenchCommunicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_message_version: int = Field(ge=1)
    expected_draft_version: int = Field(ge=1)
    expected_draft_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_source_version: int = Field(ge=1)
    expected_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: str = Field(min_length=1, max_length=1000)


class SubmitWorkbenchCommunicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_message_version: int = Field(ge=1)
    expected_draft_version: int = Field(ge=1)
    expected_draft_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_source_version: int = Field(ge=1)
    expected_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def canonical_grouped_source_identity(
    *,
    tenant_id: uuid.UUID,
    service_request_id: uuid.UUID,
    action_id: uuid.UUID,
    approved_proposal_hash: str,
    connection_id: uuid.UUID,
    company_id: int,
    partner_id: int,
    invoice_records: list[dict[str, Any]],
    execution_evidence: list[dict[str, Any]],
    source_version: int = 1,
) -> str:
    """Canonical, versioned source envelope for one customer's draft."""
    payload = {
        "schema": "workbench_collection_source_v1",
        "source_version": source_version,
        "tenant_id": str(tenant_id),
        "service_request_id": str(service_request_id),
        "action_id": str(action_id),
        "approved_proposal_hash": approved_proposal_hash,
        "connection_id": str(connection_id),
        "company_id": company_id,
        "partner_id": partner_id,
        "invoice_records": sorted(invoice_records, key=lambda item: int(item["invoice_id"])),
        "execution_evidence": sorted(execution_evidence, key=lambda item: str(item["item_id"])),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _message_out(message: WorkbenchCollectionMessage) -> dict[str, Any]:
    evidence = json.loads(message.source_evidence_json)
    records = evidence.get("records", [])
    return {
        "id": str(message.id),
        "service_request_id": str(message.service_request_id),
        "action_id": str(message.action_id),
        "partner_id": message.partner_id,
        "customer": records[0].get("customer", message.partner_name) if records else message.partner_name,
        "invoice_records": records,
        "company_id": message.company_id,
        "invoice_ids": json.loads(message.invoice_ids_json),
        "status": message.status,
        "policy_state": "awaiting_approval" if message.status == "awaiting_approval" else "allowed",
        "prepared_by": str(message.created_by_user_id),
        "prepared_at": message.created_at,
        "source": "Verified Phase 4B Odoo execution",
        "version": message.version,
        "draft_content": message.draft_content,
        "draft_version": message.draft_version,
        "draft_hash": message.draft_hash,
        "source_hash": message.source_hash,
        "source_version": message.source_version,
        "submitted_at": message.submitted_at,
        "created_at": message.created_at,
        "updated_at": message.updated_at,
        "can_edit": message.status == "draft",
        "can_submit": message.status == "draft",
    }


def _messages(db: Session, request: ServiceRequest, action: OperationAction) -> list[WorkbenchCollectionMessage]:
    return (
        db.query(WorkbenchCollectionMessage)
        .filter_by(
            tenant_id=request.tenant_id,
            service_request_id=request.id,
            action_id=action.id,
        )
        .order_by(WorkbenchCollectionMessage.partner_id, WorkbenchCollectionMessage.id)
        .all()
    )


def _load_evidence(
    db: Session,
    request: ServiceRequest,
    action: OperationAction,
) -> tuple[OperationTask, CollectionProposal, Connection, list[OperationActionExecutionItem]]:
    task = (
        db.query(OperationTask)
        .filter_by(
            id=action.task_id,
            tenant_id=request.tenant_id,
            source_type="agent_workbench",
            source_reference=str(request.id),
            source_signal=COLLECTION_FOLLOWUP_KEY,
        )
        .one_or_none()
    )
    if task is None or action.workflow_key != COLLECTION_FOLLOWUP_KEY or action.status != "succeeded":
        raise HTTPException(status_code=409, detail="A verified Workbench execution is required")
    try:
        proposal = CollectionProposal.model_validate_json(action.proposal_json)
        _, proposal_hash = canonical_collection_proposal(proposal)
    except (ValueError, TypeError):
        raise HTTPException(status_code=409, detail="Workbench approval evidence is invalid")
    if (
        proposal_hash != action.proposal_hash
        or proposal_hash != action.approved_hash
        or proposal.service_request_id != request.id
        or proposal.tenant_id != request.tenant_id
        or task.source_connection_id != proposal.connection_id
    ):
        raise HTTPException(status_code=409, detail="Workbench approval evidence is stale")
    connection = (
        db.query(Connection)
        .filter_by(id=proposal.connection_id, tenant_id=request.tenant_id, provider="odoo")
        .one_or_none()
    )
    if (
        connection is None
        or not connection.is_active
        or connection.status != "configured"
        or connection.last_test_status != "success"
        or connection.odoo_company_id != proposal.company_id
    ):
        raise HTTPException(status_code=409, detail="The verified Odoo source is unavailable")
    items = (
        db.query(OperationActionExecutionItem)
        .filter_by(action_id=action.id, task_id=task.id, tenant_id=request.tenant_id)
        .all()
    )
    expected = {int(record["invoice_id"]) for record in proposal.target_records}
    actual = {item.invoice_id for item in items}
    if (
        actual != expected
        or len(items) != len(expected)
        or not all(
            item.status == "succeeded"
            and item.external_activity_id is not None
            and item.verified_at is not None
            for item in items
        )
    ):
        raise HTTPException(status_code=409, detail="All execution targets must be verified")
    return task, proposal, connection, items


def _read_partner_ids(
    connection: Connection,
    invoice_ids: list[int],
    *,
    as_of_date,
) -> dict[int, dict[str, Any]]:
    try:
        credentials = decrypt_credentials(
            connection.encrypted_credentials,
            tenant_id=connection.tenant_id,
            connection_id=connection.id,
            encryption_version=connection.encryption_version,
        )
        auth = resolve_auth_material(connection.username, credentials)
        return {
            invoice_id: read_invoice_collection_snapshot(
                base_url=connection.base_url,
                database=connection.database_name,
                transport=connection.selected_transport,
                login=auth.login,
                secret=auth.secret,
                environment=get_settings().environment,
                company_id=connection.odoo_company_id,
                invoice_id=invoice_id,
                as_of_date=as_of_date,
            )
            for invoice_id in invoice_ids
        }
    except CollectionMessagePolicyError:
        raise
    except (
        ConnectorError,
        CredentialDecryptionError,
        EncryptionConfigError,
        AuthMaterialError,
        ValueError,
        TypeError,
    ) as exc:
        raise HTTPException(status_code=409, detail="Customer communication policy is unavailable") from exc
    finally:
        if "credentials" in locals():
            del credentials
        if "auth" in locals():
            del auth


def _same_live_record(
    record: dict[str, Any],
    live: dict[str, Any],
    company_id: int,
    source_as_of: str | None,
) -> bool:
    def dec(value: Any) -> Decimal:
        return Decimal(str(value)).normalize()
    approved_due = record.get("due_date")
    if approved_due is None:
        try:
            if source_as_of is None or not isinstance(record.get("days_overdue"), int):
                return False
            approved_due = (
                date.fromisoformat(source_as_of) - timedelta(days=record["days_overdue"])
            ).isoformat()
        except (TypeError, ValueError, OverflowError):
            return False
    approved_reference = record.get("reference", record.get("invoice_reference"))
    if approved_reference is None:
        approved_reference = record.get("invoice_number")
    if approved_reference is None:
        return False
    result = (
        int(record["customer_id"]) == int(live["partner_id"])
        and int(live["company_id"]) == company_id
        and live["move_type"] == "out_invoice"
        and live["state"] == "posted"
        and dec(record["remaining_amount"]) == dec(live["residual"])
        and (
            str(record["currency_id"]) == str(live["currency"])
            or str(record.get("currency")) == str(live["currency"])
        )
        and (
            "currency" not in record or live.get("currency_name") is None
            or str(record.get("currency")) == str(live.get("currency_name"))
        )
        and (
            str(approved_due) == str(live["due_date"])
        )
        and (
            str(approved_reference) == str(live["reference"])
        )
    )
    return result


def _static_draft(locale: str, invoice_count: int) -> str:
    if locale == "en":
        return (
            f"Dear customer، نود التذكير بوجود {invoice_count} فاتورة مستحقة. "
            "يرجى مراجعة المبلغ المستحق والتواصل معنا لترتيب السداد."
        )
    return (
        f"السادة/ العميل الكريم، نود التذكير بوجود {invoice_count} فاتورة مستحقة. "
        "يرجى مراجعة المبلغ المستحق والتواصل معنا لترتيب السداد."
    )


def _record_event(db: Session, message: WorkbenchCollectionMessage, event: str, actor: User, detail: str | None = None) -> None:
    db.add(
        WorkbenchCollectionMessageEvent(
            message_id=message.id,
            tenant_id=message.tenant_id,
            service_request_id=message.service_request_id,
            actor_type="user",
            actor_id=str(actor.id),
            event=event,
            version=message.version,
            content_hash=message.draft_hash,
            source_hash=message.source_hash,
            detail=detail,
        )
    )
    record_audit(
        db,
        action=f"workbench_collection_message.{event}",
        actor_type="user",
        actor_id=str(actor.id),
        tenant_id=message.tenant_id,
        resource_type="workbench_collection_message",
        resource_id=str(message.id),
        metadata={
            "service_request_id": str(message.service_request_id),
            "action_id": str(message.action_id),
            "partner_id": message.partner_id,
            "draft_hash": message.draft_hash,
            "source_hash": message.source_hash,
            **({"detail": detail} if detail else {}),
        },
    )


def _policy_blocked(
    db: Session, message: WorkbenchCollectionMessage | None, actor: User, code: str,
) -> HTTPException:
    if message is not None:
        _record_event(db, message, "policy_blocked", actor, code)
        db.commit()
    return HTTPException(status_code=409, detail=f"communication_policy_blocked:{code}")
def prepare_communications(
    db: Session,
    actor: User,
    request: ServiceRequest,
    action: OperationAction,
    body: PrepareWorkbenchCommunicationInput,
) -> list[dict[str, Any]]:
    _task, proposal, connection, items = _load_evidence(db, request, action)

    try:
        partner_by_invoice = _read_partner_ids(
            connection,
            sorted(int(record["invoice_id"]) for record in proposal.target_records),
            as_of_date=datetime.now(UTC).date(),
        )
    except CollectionMessagePolicyError as exc:
        raise HTTPException(
            status_code=409, detail=f"communication_policy_blocked:{exc.code or 'policy_unavailable'}"
        ) from exc
    records_by_partner: dict[int, list[dict[str, Any]]] = {}
    for record in proposal.target_records:
        invoice_id = int(record["invoice_id"])
        live = partner_by_invoice[invoice_id]
        partner_id = int(live["partner_id"])
        if not _same_live_record(
            record, live, proposal.company_id, proposal.source_as_of
        ):
            raise HTTPException(status_code=409, detail="source_changed_requires_review")
        record = {**record, "live_snapshot": live, "customer": record.get("customer", f"Customer {partner_id}")}
        records_by_partner.setdefault(partner_id, []).append(record)
    items_by_invoice = {item.invoice_id: item for item in items}
    for partner_id, records in records_by_partner.items():
        invoice_ids = sorted(int(record["invoice_id"]) for record in records)
        evidence = [
            {
                "item_id": str(items_by_invoice[invoice_id].id),
                "invoice_id": invoice_id,
                "external_activity_id": items_by_invoice[invoice_id].external_activity_id,
                "verified_at": items_by_invoice[invoice_id].verified_at.isoformat(),
            }
            for invoice_id in invoice_ids
        ]
        source_hash = canonical_grouped_source_identity(
            tenant_id=request.tenant_id,
            service_request_id=request.id,
            action_id=action.id,
            approved_proposal_hash=action.approved_hash or "",
            connection_id=connection.id,
            company_id=proposal.company_id,
            partner_id=partner_id,
            invoice_records=records,
            execution_evidence=evidence,
        )
        existing = (
            db.query(WorkbenchCollectionMessage)
            .filter_by(action_id=action.id, partner_id=partner_id, tenant_id=request.tenant_id)
            .one_or_none()
        )
        if existing is not None:
            if existing.source_hash != source_hash:
                raise HTTPException(status_code=409, detail="Communication source changed")
            continue
        content, draft_hash = canonical_collection_message(
            _static_draft(body.locale, len(records)), 1
        )
        message = WorkbenchCollectionMessage(
            tenant_id=request.tenant_id,
            service_request_id=request.id,
            action_id=action.id,
            connection_id=connection.id,
            company_id=proposal.company_id,
            partner_id=partner_id,
            partner_name=str(records[0].get("customer") or f"Customer {partner_id}"),
            invoice_ids_json=json.dumps(invoice_ids, separators=(",", ":")),
            source_evidence_json=json.dumps(
                {"schema": "workbench_collection_source_v1", "records": records, "evidence": evidence},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ),
            draft_content=content,
            draft_hash=draft_hash,
            source_hash=source_hash,
            idempotency_marker=sha256(f"{action.id}:{partner_id}:phase4c".encode()).hexdigest(),
            created_by_user_id=actor.id,
        )
        db.add(message)
        db.flush()
        _record_event(db, message, "generated", actor)
        _record_event(db, message, "policy_checked", actor, "allowed")
    db.commit()
    return [_message_out(message) for message in _messages(db, request, action)]


def edit_communication(
    db: Session, actor: User, request: ServiceRequest, message_id: uuid.UUID,
    body: EditWorkbenchCommunicationInput,
) -> dict[str, Any]:
    message = (
        db.query(WorkbenchCollectionMessage)
        .filter_by(id=message_id, tenant_id=request.tenant_id, service_request_id=request.id)
        .with_for_update().one_or_none()
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Communication draft not found")
    if (
        message.status != "draft"
        or message.version != body.expected_message_version
        or message.draft_version != body.expected_draft_version
        or message.draft_hash != body.expected_draft_hash
        or message.source_version != body.expected_source_version
        or message.source_hash != body.expected_source_hash
    ):
        raise HTTPException(status_code=409, detail="Communication draft has been modified or submitted")
    content, digest = canonical_collection_message(body.content, message.draft_version + 1)
    message.draft_content = content
    message.draft_hash = digest
    message.draft_version += 1
    message.version += 1
    _record_event(db, message, "regenerated", actor)
    db.commit()
    return _message_out(message)


def submit_communication(
    db: Session, actor: User, request: ServiceRequest, message_id: uuid.UUID,
    body: SubmitWorkbenchCommunicationInput,
) -> dict[str, Any]:
    message = (
        db.query(WorkbenchCollectionMessage)
        .filter_by(id=message_id, tenant_id=request.tenant_id, service_request_id=request.id)
        .with_for_update().one_or_none()
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Communication draft not found")
    if (
        message.status != "draft"
        or message.version != body.expected_message_version
        or message.draft_version != body.expected_draft_version
        or message.draft_hash != body.expected_draft_hash
        or message.source_version != body.expected_source_version
        or message.source_hash != body.expected_source_hash
    ):
        raise HTTPException(status_code=409, detail="Communication draft has been modified")
    action = (
        db.query(OperationAction)
        .join(OperationTask, OperationTask.id == OperationAction.task_id)
        .filter(
            OperationAction.id == message.action_id,
            OperationAction.tenant_id == request.tenant_id,
            OperationTask.tenant_id == request.tenant_id,
            OperationTask.source_reference == str(request.id),
            OperationTask.source_type == "agent_workbench",
            OperationTask.source_signal == COLLECTION_FOLLOWUP_KEY,
        )
        .one_or_none()
    )
    if action is None:
        raise HTTPException(status_code=404, detail="Communication source not found")
    try:
        _task, proposal, connection, _items = _load_evidence(db, request, action)
    except CollectionMessagePolicyError as exc:
        raise _policy_blocked(db, message, actor, exc.code or "policy_unavailable") from exc
    try:
        partners = _read_partner_ids(
            connection, json.loads(message.invoice_ids_json), as_of_date=datetime.now(UTC).date()
        )
    except CollectionMessagePolicyError as exc:
        raise _policy_blocked(db, message, actor, exc.code or "policy_unavailable") from exc
    if {int(snapshot["partner_id"]) for snapshot in partners.values()} != {message.partner_id}:
        raise HTTPException(status_code=409, detail="source_changed_requires_review")
    records = json.loads(message.source_evidence_json)["records"]
    evidence = json.loads(message.source_evidence_json)["evidence"]
    current_records = [
        {**record, "live_snapshot": partners[int(record["invoice_id"])]}
        for record in records
    ]
    current_hash = canonical_grouped_source_identity(
        tenant_id=request.tenant_id, service_request_id=request.id, action_id=message.action_id,
        approved_proposal_hash=db.get(OperationAction, message.action_id).approved_hash or "",
        connection_id=connection.id, company_id=proposal.company_id, partner_id=message.partner_id,
        invoice_records=current_records, execution_evidence=evidence,
    )
    if current_hash != message.source_hash:
        raise HTTPException(status_code=409, detail="source_changed_requires_review")
    message.status = "awaiting_approval"
    message.submitted_by_user_id = actor.id
    message.submitted_at = datetime.now(UTC)
    message.version += 1
    _record_event(db, message, "submitted", actor)
    db.commit()
    return _message_out(message)
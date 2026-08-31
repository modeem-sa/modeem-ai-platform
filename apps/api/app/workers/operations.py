"""Dedicated polling worker; external writes are never made in request handlers."""

import json
import time
import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.content_manager.provider import (
    OpenAICompatibleProvider,
    ProviderFailureError,
    ProviderUnavailableError,
)
from app.core.config import get_settings
from app.db.base import get_session_factory
from app.integrations.odoo.activity_writer import create_invoice_activity
from app.integrations.odoo.errors import ConnectorError
from app.integrations.odoo.invoice_chatter_collection import (
    CollectionMessagePolicyError,
    deliver_invoice_collection_message,
    read_invoice_collection_target,
)
from app.models import (
    CollectionMessage,
    CollectionMessageEvent,
    Connection,
    OperationAction,
    OperationActionHistory,
    OperationTask,
    User,
)
from app.operations.ai_proposal import (
    InvoiceActivityProposal,
    canonical_proposal,
    executable_invoice_activity_proposal,
)
from app.operations.automation_catalog import effective_config
from app.operations.collection_message import (
    canonical_collection_message,
    canonical_collection_source_identity,
)
from app.operations.odoo_sync import scan_overdue_invoices
from app.operations.proposals import (
    OperationsProposalService,
    invoice_summary_from_snapshot,
)
from app.operations.recurring import generate_occurrences
from app.services.audit import record_audit
from app.services.connection_auth import AuthMaterialError, resolve_auth_material
from app.services.credential_crypto import (
    CredentialDecryptionError,
    EncryptionConfigError,
    decrypt_credentials,
)

_AI_AUTOMATION_RETRY_AFTER = 0.0


def generate_missing_ai_proposals_once() -> int:
    """Prepare and submit bounded AI proposals for new overdue-invoice tasks."""
    global _AI_AUTOMATION_RETRY_AFTER

    if time.monotonic() < _AI_AUTOMATION_RETRY_AFTER:
        return 0
    session = get_session_factory()()
    generated = 0
    try:
        if (
            session.bind
            and session.bind.dialect.name == "postgresql"
            and not session.execute(text("SELECT pg_try_advisory_xact_lock(810006)")).scalar()
        ):
            return 0
        tasks = (
            session.query(OperationTask)
            .outerjoin(
                OperationAction,
                (OperationAction.task_id == OperationTask.id)
                & (OperationAction.tenant_id == OperationTask.tenant_id),
            )
            .filter(
                OperationTask.source_type == "odoo",
                OperationTask.source_signal == "overdue_customer_invoice",
                OperationTask.source_record_id.is_not(None),
                OperationTask.source_snapshot_json.is_not(None),
                OperationAction.id.is_(None),
            )
            .order_by(OperationTask.created_at.asc(), OperationTask.id.asc())
            .limit(10)
            .all()
        )
        if not tasks:
            return 0
        eligible_tasks: list[tuple[OperationTask, dict[str, object]]] = []
        for task in tasks:
            config = effective_config(
                session, task.tenant_id, "finance.overdue_invoice_followup"
            )
            modes = config["step_modes"]
            assert isinstance(modes, dict)
            if not config["enabled"] or modes["prepare_draft"] == "manual":
                continue
            eligible_tasks.append((task, config))
        if not eligible_tasks:
            return 0
        try:
            provider = OpenAICompatibleProvider.from_environment()
        except ProviderUnavailableError:
            _AI_AUTOMATION_RETRY_AFTER = time.monotonic() + 300
            return 0
        service = OperationsProposalService(provider)
        for task, config in eligible_tasks:
            modes = config["step_modes"]
            assert isinstance(modes, dict)
            try:
                snapshot = json.loads(task.source_snapshot_json or "")
                summary, company_id, activity_type_id = invoice_summary_from_snapshot(
                    tenant_id=task.tenant_id,
                    snapshot=snapshot,
                    as_of_date=datetime.now(UTC).date(),
                )
                draft = service.propose(tenant_id=task.tenant_id, summary=summary)
                proposal = executable_invoice_activity_proposal(
                    draft,
                    company_id=company_id,
                    invoice_id=task.source_record_id,
                    activity_type_id=activity_type_id,
                )
                payload, digest = canonical_proposal(proposal)
            except ProviderFailureError:
                _AI_AUTOMATION_RETRY_AFTER = time.monotonic() + 300
                break
            except (ValidationError, ValueError, TypeError, json.JSONDecodeError):
                continue

            action = OperationAction(
                tenant_id=task.tenant_id,
                task_id=task.id,
                proposal_json=payload,
                proposal_hash=digest,
                status="proposed",
                version=1,
                idempotency_marker=uuid.uuid4().hex,
                workflow_key="finance.overdue_invoice_followup",
                workflow_config_version=config["version"],
            )
            try:
                with session.begin_nested():
                    session.add(action)
                    session.flush()
            except IntegrityError:
                # The API or another safe generator won the race. The unique
                # task constraint remains the final idempotency boundary.
                continue
            session.add(
                OperationActionHistory(
                    action_id=action.id,
                    task_id=task.id,
                    tenant_id=task.tenant_id,
                    actor_type="system",
                    actor_id="operations-automation",
                    event="generated",
                    version=action.version,
                    status=action.status,
                    proposal_hash=action.proposal_hash,
                    detail="automatic",
                )
            )
            if modes["submit_for_approval"] == "automatic":
                action.status = "awaiting_approval"
                action.version += 1
                session.add(
                    OperationActionHistory(
                        action_id=action.id,
                        task_id=task.id,
                        tenant_id=task.tenant_id,
                        actor_type="system",
                        actor_id="operations-automation",
                        event="submitted",
                        version=action.version,
                        status=action.status,
                        proposal_hash=action.proposal_hash,
                        detail="automatic",
                    )
                )
            record_audit(
                session,
                action="operation_action.automated_proposal_ready",
                actor_type="system",
                actor_id="operations-automation",
                tenant_id=task.tenant_id,
                resource_type="operation_action",
                resource_id=str(action.id),
                metadata={"proposal_hash": digest},
            )
            generated += 1
        session.commit()
        return generated
    finally:
        session.close()


def run_queued_actions_once() -> int:
    session = get_session_factory()()
    done = 0
    try:
        # PostgreSQL singleton guard; sqlite test databases simply run one process.
        if (
            session.bind
            and session.bind.dialect.name == "postgresql"
            and not session.execute(text("SELECT pg_try_advisory_xact_lock(810005)")).scalar()
        ):
            return 0
        action_ids = [
            row[0]
            for row in session.query(OperationAction.id)
            .filter_by(status="queued")
            .limit(20)
            .all()
        ]
        for action_id in action_ids:
            action = session.get(OperationAction, action_id)
            if action is None:
                continue
            task = (
                session.query(OperationTask)
                .filter_by(id=action.task_id, tenant_id=action.tenant_id)
                .one_or_none()
            )
            if task is None or task.source_connection_id is None or task.source_record_id is None:
                _fail_action(session, action, "source_validation_failed")
                continue
            # Connection is always locked before the action. Connection PATCH uses
            # the same ordering, so a company-scope change cannot race execution.
            conn = (
                session.query(Connection)
                .filter_by(id=task.source_connection_id, tenant_id=action.tenant_id)
                .with_for_update()
                .one_or_none()
            )
            task = (
                session.query(OperationTask)
                .filter_by(id=action.task_id, tenant_id=action.tenant_id)
                .populate_existing()
                .with_for_update()
                .one_or_none()
            )
            action = (
                session.query(OperationAction)
                .filter_by(id=action_id, status="queued")
                .populate_existing()
                .with_for_update()
                .one_or_none()
            )
            if action is None:
                continue
            if (
                task is None
                or conn is None
                or task.source_connection_id != conn.id
                or task.source_record_id is None
            ):
                _fail_action(session, action, "source_validation_failed")
                continue
            # Older queued records predate workflow metadata.  They are treated
            # as the fixed invoice workflow but have no historical version to
            # compare, preserving approved work while still honoring a disable.
            workflow_key = action.workflow_key or "finance.overdue_invoice_followup"
            try:
                config = effective_config(session, action.tenant_id, workflow_key)
            except ValueError:
                _fail_action(session, action, "workflow_config_invalid")
                continue
            if not config["enabled"] or (
                action.workflow_config_version is not None
                and action.workflow_config_version != config["version"]
            ):
                _fail_action(session, action, "workflow_config_changed")
                continue
            if (
                not conn.is_active
                or conn.last_test_status != "success"
                or conn.selected_transport not in ("xmlrpc", "json2")
            ):
                _fail_action(session, action, "connection_unavailable")
                continue
            try:
                proposal = InvoiceActivityProposal.model_validate_json(action.proposal_json)
                _, digest = canonical_proposal(proposal)
                snapshot = json.loads(task.source_snapshot_json or "")
                if not isinstance(snapshot, dict):
                    _fail_action(session, action, "proposal_validation_failed")
                    continue
                snapshot_company_id = snapshot.get("company_id")
                if (
                    digest != action.proposal_hash
                    or digest != action.approved_hash
                    or task.source_record_id != proposal.invoice_id
                    or isinstance(snapshot_company_id, bool)
                    or not isinstance(snapshot_company_id, int)
                    or snapshot_company_id != proposal.company_id
                    or conn.odoo_company_id != proposal.company_id
                ):
                    _fail_action(session, action, "proposal_validation_failed")
                    continue
                creds = decrypt_credentials(
                    conn.encrypted_credentials,
                    tenant_id=conn.tenant_id,
                    connection_id=conn.id,
                    encryption_version=conn.encryption_version,
                )
                auth = resolve_auth_material(conn.username, creds)
                action.status = "executing"
                action.attempt_count += 1
                action.version += 1
                _record_worker_history(session, action, "executing")
                session.flush()
                receipt = create_invoice_activity(
                    base_url=conn.base_url,
                    database=conn.database_name,
                    transport=conn.selected_transport,
                    login=auth.login,
                    secret=auth.secret,
                    environment=get_settings().environment,
                    company_id=proposal.company_id,
                    invoice_id=proposal.invoice_id,
                    activity_type_id=proposal.activity_type_id,
                    summary=proposal.title,
                    date_deadline=proposal.date_deadline.isoformat(),
                    idempotency_marker=action.idempotency_marker,
                )
                action.external_activity_id = receipt["activity_id"]
                action.verified_at = datetime.now(UTC)
                action.status = "succeeded"
                action.error = None
                action.version += 1
                _record_worker_history(session, action, "succeeded")
                done += 1
            except (
                ConnectorError,
                CredentialDecryptionError,
                EncryptionConfigError,
                AuthMaterialError,
                ValidationError,
                ValueError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
            ):
                action.version += 1
                if action.attempt_count < 3:
                    action.error = "external_execution_failed"
                    action.status = "queued"
                    _record_worker_history(
                        session, action, "retry_queued", detail="external_execution_failed"
                    )
                else:
                    action.error = "external_execution_failed"
                    action.status = "failed"
                    _record_worker_history(
                        session, action, "failed", detail="external_execution_failed"
                    )
        session.commit()
    finally:
        session.close()
    return done


def _record_worker_history(
    session, action: OperationAction, event: str, detail: str | None = None
) -> None:
    session.add(
        OperationActionHistory(
            action_id=action.id,
            task_id=action.task_id,
            tenant_id=action.tenant_id,
            actor_type="worker",
            actor_id="operations-worker",
            event=event,
            version=action.version,
            status=action.status,
            proposal_hash=action.proposal_hash,
            detail=detail,
        )
    )


def _fail_action(session, action: OperationAction, detail: str) -> None:
    action.status = "failed"
    action.error = detail
    action.version += 1
    _record_worker_history(session, action, "failed", detail=detail)


def run_queued_collection_messages_once() -> int:
    """Process only the dedicated fixed invoice-chatter delivery queue."""
    session = get_session_factory()()
    delivered = 0
    try:
        if (
            session.bind
            and session.bind.dialect.name == "postgresql"
            and not session.execute(text("SELECT pg_try_advisory_xact_lock(810041)")).scalar()
        ):
            return 0
        message_ids = [
            row[0]
            for row in session.query(CollectionMessage.id)
            .filter_by(status="queued")
            .limit(20)
            .all()
        ]
        for message_id in message_ids:
            message = session.query(CollectionMessage).filter_by(
                id=message_id, status="queued"
            ).with_for_update().one_or_none()
            if message is None:
                continue
            message.status = "sending"
            message.attempt_count += 1
            message.version += 1
            _record_message_worker_event(session, message, "sending")
            session.flush()
            task = session.query(OperationTask).filter_by(
                id=message.task_id, tenant_id=message.tenant_id
            ).with_for_update().one_or_none()
            if task is None or task.source_connection_id is None or task.source_record_id is None:
                _fail_message(session, message, "source_validation_failed")
                continue
            connection = session.query(Connection).filter_by(
                id=task.source_connection_id, tenant_id=message.tenant_id
            ).with_for_update().one_or_none()
            if (
                connection is None
                or not connection.is_active
                or connection.last_test_status != "success"
                or connection.selected_transport not in ("xmlrpc", "json2")
                or connection.odoo_company_id is None
            ):
                _fail_message(session, message, "connection_unavailable")
                continue
            try:
                snapshot = json.loads(task.source_snapshot_json or "")
                snapshot_company_id = snapshot.get("company_id") if isinstance(snapshot, dict) else None
                approved_content, approved_digest = canonical_collection_message(
                    message.approved_content or "", message.approved_draft_version or 0
                )
                if (
                    approved_digest != message.approved_hash
                    or message.approved_hash != message.draft_hash
                    or message.approved_draft_version != message.draft_version
                    or message.approved_source_hash != message.source_hash
                    or message.approved_source_version != message.source_version
                    or snapshot_company_id != connection.odoo_company_id
                ):
                    _fail_message(session, message, "approval_validation_failed")
                    continue
                credentials = decrypt_credentials(
                    connection.encrypted_credentials,
                    tenant_id=connection.tenant_id,
                    connection_id=connection.id,
                    encryption_version=connection.encryption_version,
                )
                auth = resolve_auth_material(connection.username, credentials)
                partner_id = read_invoice_collection_target(
                    base_url=connection.base_url,
                    database=connection.database_name,
                    transport=connection.selected_transport,
                    login=auth.login,
                    secret=auth.secret,
                    environment=get_settings().environment,
                    company_id=connection.odoo_company_id,
                    invoice_id=task.source_record_id,
                    as_of_date=datetime.now(UTC).date(),
                    now=datetime.now(UTC),
                )
                _record_message_worker_event(
                    session, message, "policy_checked", detail="allowed"
                )
                source_hash = canonical_collection_source_identity(
                    connection_id=str(connection.id),
                    company_id=connection.odoo_company_id,
                    invoice_id=task.source_record_id,
                    partner_id=partner_id,
                    source_version=message.approved_source_version or 0,
                    source_snapshot=snapshot,
                )
                if (
                    source_hash != message.approved_source_hash
                    or partner_id != message.approved_partner_id
                ):
                    _fail_message(session, message, "source_identity_changed")
                    continue
                receipt = deliver_invoice_collection_message(
                    base_url=connection.base_url,
                    database=connection.database_name,
                    transport=connection.selected_transport,
                    login=auth.login,
                    secret=auth.secret,
                    environment=get_settings().environment,
                    company_id=connection.odoo_company_id,
                    invoice_id=task.source_record_id,
                    content=approved_content,
                    idempotency_marker=message.idempotency_marker,
                    expected_partner_id=message.approved_partner_id,
                    as_of_date=datetime.now(UTC).date(),
                    now=datetime.now(UTC),
                )
                message.status = "verifying"
                message.external_message_id = receipt["message_id"]
                message.version += 1
                _record_message_worker_event(session, message, "sent")
                _record_message_worker_event(session, message, "verifying")
                if receipt.get("verified") is not True:
                    raise ConnectorError("unsupported_response", "message not verified")
                message.verified_at = datetime.now(UTC)
                message.status = "succeeded"
                message.error = None
                message.version += 1
                _record_message_worker_event(session, message, "verified")
                _record_message_worker_event(session, message, "succeeded")
                delivered += 1
            except CollectionMessagePolicyError as exc:
                if isinstance(exc.code, str) and exc.code:
                    message.version += 1
                    message.status = "failed"
                    message.error = exc.code
                    _record_message_worker_event(
                        session, message, "policy_checked", detail=exc.code
                    )
                    _record_message_worker_event(
                        session, message, "failed", detail=exc.code
                    )
                else:
                    _record_delivery_failure(session, message)
            except (
                ConnectorError,
                CredentialDecryptionError,
                EncryptionConfigError,
                AuthMaterialError,
                ValidationError,
                ValueError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
            ):
                _record_delivery_failure(session, message)
        session.commit()
        return delivered
    finally:
        session.close()


def _record_message_worker_event(
    session,
    message: CollectionMessage,
    event: str,
    detail: str | None = None,
) -> None:
    session.add(
        CollectionMessageEvent(
            message_id=message.id,
            task_id=message.task_id,
            tenant_id=message.tenant_id,
            actor_type="worker",
            actor_id="collection-message-worker",
            event=event,
            version=message.version,
            status=message.status,
            content_hash=message.approved_hash or message.draft_hash,
            detail=detail,
        )
    )


def _record_delivery_failure(session, message: CollectionMessage) -> None:
    message.version += 1
    message.error = "delivery_failed"
    if message.attempt_count < 3:
        message.status = "queued"
        _record_message_worker_event(
            session, message, "retry_queued", detail="delivery_failed"
        )
    else:
        message.status = "failed"
        _record_message_worker_event(
            session, message, "failed", detail="delivery_failed"
        )


def _fail_message(session, message: CollectionMessage, detail: str) -> None:
    message.status = "failed"
    message.error = detail
    message.version += 1
    _record_message_worker_event(session, message, "failed", detail=detail)


def scan_connections_once() -> int:
    """Scan each explicitly company-scoped connection independently."""
    session = get_session_factory()()
    scanned = 0
    try:
        connections = session.query(Connection).filter(
            Connection.provider == "odoo", Connection.is_active.is_(True),
            Connection.last_test_status == "success",
            Connection.selected_transport.in_(("xmlrpc", "json2")),
            Connection.odoo_company_id.is_not(None),
        ).all()
        for conn in connections:
            actor = session.get(User, conn.created_by_user_id) if conn.created_by_user_id else None
            if actor is None or not actor.is_active:
                continue
            try:
                created = scan_overdue_invoices(
                    session, connection=conn, company_id=conn.odoo_company_id, actor=actor
                )
                record_audit(session, action="connection.overdue_invoice_sync",
                    actor_type="worker", actor_id=str(conn.id), tenant_id=conn.tenant_id,
                    resource_type="connection", resource_id=str(conn.id),
                    metadata={"company_id": conn.odoo_company_id, "created": created})
                session.commit()
                scanned += 1
            except (ConnectorError, CredentialDecryptionError, EncryptionConfigError,
                    AuthMaterialError, ValueError, TypeError):
                session.rollback()
                # The exception may contain upstream detail; audit only a static outcome.
                record_audit(session, action="connection.overdue_invoice_sync_failed",
                    actor_type="worker", actor_id=str(conn.id), tenant_id=conn.tenant_id,
                    resource_type="connection", resource_id=str(conn.id),
                    metadata={"company_id": conn.odoo_company_id})
                session.commit()
        return scanned
    finally:
        session.close()


def main() -> None:
    while True:
        generate_missing_ai_proposals_once()
        run_queued_actions_once()
        run_queued_collection_messages_once()
        scan_connections_once()
        session = get_session_factory()()
        try:
            generate_occurrences(session)
            session.commit()
        finally:
            session.close()
        time.sleep(15)

if __name__ == "__main__":
    main()
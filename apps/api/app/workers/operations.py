"""Dedicated polling worker; external writes are never made in request handlers."""

import json
import time
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import text

from app.core.config import get_settings
from app.db.base import get_session_factory
from app.integrations.odoo.activity_writer import create_invoice_activity
from app.integrations.odoo.errors import ConnectorError
from app.models import Connection, OperationAction, OperationActionHistory, OperationTask, User
from app.operations.ai_proposal import InvoiceActivityProposal, canonical_proposal
from app.operations.odoo_sync import scan_overdue_invoices
from app.operations.recurring import generate_occurrences
from app.services.audit import record_audit
from app.services.connection_auth import AuthMaterialError, resolve_auth_material
from app.services.credential_crypto import (
    CredentialDecryptionError,
    EncryptionConfigError,
    decrypt_credentials,
)


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
        run_queued_actions_once()
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
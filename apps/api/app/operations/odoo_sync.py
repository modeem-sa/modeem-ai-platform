"""Fixed, bounded overdue-invoice signal scanner (no caller supplied Odoo DSL)."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.odoo import http as safe_http
from app.integrations.odoo import json2, legacy_xmlrpc
from app.integrations.odoo.errors import ConnectorError
from app.models import Connection, OperationTask, OperationTaskHistory, User
from app.services.connection_auth import resolve_auth_material
from app.services.credential_crypto import decrypt_credentials

PAGE_SIZE = 50
SIGNAL = "overdue_customer_invoice"


def _relation(value: Any) -> tuple[int, str]:
    if not isinstance(value, (list, tuple)) or len(value) != 2 or not isinstance(value[0], int) or not isinstance(value[1], str):
        raise ConnectorError("unsupported_response", "invalid relation")
    return value[0], value[1][:255]


def scan_overdue_invoices(db: Session, *, connection: Connection, company_id: int,
                          actor: User, max_pages: int = 4) -> int:
    """Upsert real posted invoices due today; all query inputs are server-owned."""
    if company_id < 1 or not connection.is_active or connection.provider != "odoo" or connection.last_test_status != "success" or connection.selected_transport not in ("xmlrpc", "json2"):
        raise ValueError("connection is not ready for sync")
    credentials = decrypt_credentials(connection.encrypted_credentials, tenant_id=connection.tenant_id, connection_id=connection.id, encryption_version=connection.encryption_version)
    auth = resolve_auth_material(connection.username, credentials)
    created = 0
    fields = ["id", "name", "partner_id", "invoice_date_due", "currency_id", "amount_total", "amount_residual", "payment_state", "company_id"]
    domain = [["company_id", "=", company_id], ["move_type", "=", "out_invoice"], ["state", "=", "posted"], ["invoice_date_due", "!=", False]]
    today = datetime.now(UTC).date().isoformat()
    try:
        with safe_http.build_client(get_settings().environment) as client:
            for page in range(max_pages):
                offset = page * PAGE_SIZE
                if connection.selected_transport == "json2":
                    rows = json2.search_read(client, connection.base_url, connection.database_name, auth.secret, model="account.move", domain=domain, fields=fields, offset=offset, limit=PAGE_SIZE, order="id asc")
                else:
                    rows = legacy_xmlrpc.search_read(client, connection.base_url, connection.database_name, auth.login, auth.secret, model="account.move", domain=domain, fields=fields, offset=offset, limit=PAGE_SIZE, order="id asc")
                if not isinstance(rows, list): raise ConnectorError("unsupported_response", "expected list")
                for row in rows:
                    if not isinstance(row, dict) or not isinstance(row.get("id"), int): raise ConnectorError("unsupported_response", "invalid invoice")
                    due = row.get("invoice_date_due")
                    residual = row.get("amount_residual")
                    if not isinstance(due, str) or due > today or isinstance(residual, bool) or not isinstance(residual, (int, float)) or Decimal(str(residual)) <= 0: continue
                    partner_id, partner_name = _relation(row["partner_id"]); currency_id, currency_name = _relation(row["currency_id"]); row_company, _ = _relation(row["company_id"])
                    if row_company != company_id: raise ConnectorError("unsupported_response", "company mismatch")
                    snapshot = {"company_id": company_id, "invoice_number": str(row.get("name") or "")[:255], "partner_display_name": partner_name, "due_date": due, "currency": currency_name[:16], "total": str(row.get("amount_total")), "residual": str(residual), "payment_state": str(row.get("payment_state") or "")[:32], "partner_id": partner_id, "currency_id": currency_id}
                    task = db.query(OperationTask).filter_by(tenant_id=connection.tenant_id, source_connection_id=connection.id, source_record_id=row["id"], source_signal=SIGNAL).one_or_none()
                    if task is None:
                        task = OperationTask(tenant_id=connection.tenant_id, title=f"Follow up invoice {snapshot['invoice_number']}"[:255], description=f"Overdue customer invoice for {partner_name}"[:10000], category="financial", priority="high", created_by_user_id=actor.id, source_type="odoo", source_connection_id=connection.id, source_record_id=row["id"], source_signal=SIGNAL, source_reference=snapshot["invoice_number"], source_snapshot_json=json.dumps(snapshot, sort_keys=True), source_synced_at=datetime.now(UTC), source_sync_state="current")
                        db.add(task); created += 1
                        db.flush()
                        db.add(OperationTaskHistory(task_id=task.id, tenant_id=task.tenant_id,
                               actor_user_id=actor.id, action="source_synced", from_status=None,
                               to_status=task.status, version=task.version, note="Odoo overdue invoice signal"))
                    else:
                        task.source_reference = snapshot["invoice_number"]; task.source_snapshot_json = json.dumps(snapshot, sort_keys=True); task.source_synced_at = datetime.now(UTC); task.source_sync_state = "current"
                if len(rows) < PAGE_SIZE: break
    finally:
        del credentials, auth
    return created
"""Fixed Odoo adapter for one customer-invoice chatter collection message."""

import html
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from . import http as safe_http
from . import json2, legacy_xmlrpc, security
from .errors import ConnectorError

_TRANSPORTS = ("xmlrpc", "json2")
_MARKER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,63}")
_CONTACT_POLICY_FIELDS = ("id", "opt_out", "tz")
_CONTACT_WINDOW_START_MINUTE = 8 * 60
_CONTACT_WINDOW_END_MINUTE = 20 * 60
_POLICY_CODES = frozenset({"contact_opted_out", "outside_contact_hours", "policy_unavailable"})


class CollectionMessagePolicyError(Exception):
    """A safe, static reason why a collection message cannot proceed."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def _positive(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 2_147_483_647:
        raise CollectionMessagePolicyError(f"{name} must be a positive integer")
    return value


def _body(content: Any, marker: Any) -> tuple[str, str]:
    if not isinstance(content, str) or not 0 < len(content) <= 1000:
        raise CollectionMessagePolicyError("content is invalid")
    if any(ord(char) < 32 and char not in ("\n", "\t") for char in content):
        raise CollectionMessagePolicyError("content contains control characters")
    if not isinstance(marker, str) or _MARKER_RE.fullmatch(marker) is None:
        raise CollectionMessagePolicyError("idempotency marker is invalid")
    return f"{html.escape(content)}<br/><span>[Modeem-Collection:{marker}]</span>", marker


def _unwrap(response: httpx.Response) -> Any:
    if response.status_code != 200:
        raise ConnectorError("unsupported_response", "unexpected status")
    try:
        raw = response.json()
    except ValueError as exc:
        raise ConnectorError("unsupported_response", "invalid JSON") from exc
    return raw.get("result") if isinstance(raw, dict) and "result" in raw else raw


def _search_read(client, *, base_url, database, transport, login, secret, model, domain, fields):
    if transport == "json2":
        return json2.search_read(client, base_url, database, secret, model=model, domain=domain,
                                 fields=fields, offset=0, limit=2, order="id asc")
    return legacy_xmlrpc.search_read(client, base_url, database, login, secret, model=model,
                                     domain=domain, fields=fields, offset=0, limit=2, order="id asc")


def _invoice(
    client, *, base_url, database, transport, login, secret, company_id, invoice_id,
    as_of_date, now: datetime | None = None,
) -> int:
    rows = _search_read(
        client, base_url=base_url, database=database, transport=transport, login=login,
        secret=secret, model="account.move",
        domain=[["id", "=", invoice_id], ["company_id", "=", company_id],
                ["move_type", "=", "out_invoice"], ["state", "=", "posted"]],
        fields=[
            "id", "company_id", "move_type", "state", "amount_residual",
            "invoice_date_due", "commercial_partner_id",
        ],
    )
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise CollectionMessagePolicyError("customer invoice is unavailable")
    row = rows[0]
    if row.get("move_type") != "out_invoice" or row.get("state") != "posted":
        raise CollectionMessagePolicyError("only posted customer invoices are eligible")
    company = row.get("company_id")
    if (
        not isinstance(company, (list, tuple))
        or len(company) != 2
        or company[0] != company_id
    ):
        raise ConnectorError("unsupported_response", "invoice company verification mismatch")
    try:
        residual = Decimal(str(row.get("amount_residual")))
        due_date = date.fromisoformat(row.get("invoice_date_due"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CollectionMessagePolicyError("invoice collectible state is invalid") from exc
    if not residual.is_finite() or residual <= 0:
        raise CollectionMessagePolicyError("invoice has no collectible residual")
    if not isinstance(as_of_date, date) or due_date >= as_of_date:
        raise CollectionMessagePolicyError("invoice is not overdue")
    relation = row.get("commercial_partner_id")
    if (row.get("id") != invoice_id or not isinstance(relation, (list, tuple))
            or len(relation) != 2 or isinstance(relation[0], bool)
            or not isinstance(relation[0], int) or relation[0] < 1):
        raise ConnectorError("unsupported_response", "invoice verification mismatch")
    partner_id = relation[0]
    partner_rows = _search_read(
        client, base_url=base_url, database=database, transport=transport, login=login,
        secret=secret, model="res.partner", domain=[["id", "=", partner_id]],
        fields=list(_CONTACT_POLICY_FIELDS),
    )
    if not isinstance(partner_rows, list) or len(partner_rows) != 1 or not isinstance(partner_rows[0], dict):
        raise CollectionMessagePolicyError(
            "customer communication policy is unavailable", code="policy_unavailable"
        )
    partner = partner_rows[0]
    if partner.get("id") != partner_id or not isinstance(partner.get("opt_out"), bool):
        raise CollectionMessagePolicyError(
            "customer communication policy is unavailable", code="policy_unavailable"
        )
    if partner["opt_out"]:
        raise CollectionMessagePolicyError(
            "customer has opted out of contact", code="contact_opted_out"
        )

    timezone_name = partner.get("tz")
    if not isinstance(timezone_name, str) or not timezone_name or len(timezone_name) > 64:
        raise CollectionMessagePolicyError(
            "customer communication policy is unavailable", code="policy_unavailable"
        )
    try:
        timezone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CollectionMessagePolicyError(
            "customer communication policy is unavailable", code="policy_unavailable"
        ) from exc
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise CollectionMessagePolicyError(
            "customer communication policy is unavailable", code="policy_unavailable"
        )
    local_now = current.astimezone(timezone)
    local_minute = local_now.hour * 60 + local_now.minute
    if not _CONTACT_WINDOW_START_MINUTE <= local_minute < _CONTACT_WINDOW_END_MINUTE:
        raise CollectionMessagePolicyError(
            "customer is outside the permitted contact hours", code="outside_contact_hours"
        )
    return partner_id


def read_invoice_collection_target(
    *, base_url: str, database: str | None, transport: str, login: str, secret: str,
    environment: str, company_id: int, invoice_id: int, as_of_date: date,
    now: datetime | None = None,
) -> int:
    """Reread invoice eligibility and the trusted communication policy before approval/send."""
    company_id = _positive(company_id, "company_id")
    invoice_id = _positive(invoice_id, "invoice_id")
    if transport not in _TRANSPORTS:
        raise ConnectorError("invalid_configuration", "stale transport")
    security.enforce_outbound_policy(base_url, environment=environment)
    with safe_http.build_client(environment) as client:
        return _invoice(client, base_url=base_url, database=database, transport=transport,
                        login=login, secret=secret, company_id=company_id,
                        invoice_id=invoice_id, as_of_date=as_of_date, now=now)


def _find(
    client, *, base_url, database, transport, login, secret, invoice_id, marker,
    expected_body, expected_partner_id,
) -> int | None:
    tag = f"[Modeem-Collection:{marker}]"
    rows = _search_read(
        client, base_url=base_url, database=database, transport=transport, login=login,
        secret=secret, model="mail.message",
        domain=[["model", "=", "account.move"], ["res_id", "=", invoice_id], ["body", "ilike", tag]],
        fields=["id", "model", "res_id", "body", "partner_ids"],
    )
    if not isinstance(rows, list) or len(rows) > 1:
        raise ConnectorError("unsupported_response", "message reconciliation was not unique")
    if not rows:
        return None
    row = rows[0]
    if (not isinstance(row, dict) or isinstance(row.get("id"), bool)
            or not isinstance(row.get("id"), int) or row["id"] < 1
            or row.get("model") != "account.move" or row.get("res_id") != invoice_id
            or not isinstance(row.get("body"), str) or tag not in row["body"]
            or expected_body not in row["body"]
            or not isinstance(row.get("partner_ids"), list)
            or expected_partner_id not in row["partner_ids"]):
        raise ConnectorError("unsupported_response", "message verification mismatch")
    return row["id"]


def deliver_invoice_collection_message(
    *, base_url: str, database: str | None, transport: str, login: str, secret: str,
    environment: str, company_id: int, invoice_id: int, content: str,
    idempotency_marker: str, expected_partner_id: int, as_of_date: date,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reconcile, post with a server-derived invoice customer, then reread."""
    company_id = _positive(company_id, "company_id")
    invoice_id = _positive(invoice_id, "invoice_id")
    body, marker = _body(content, idempotency_marker)
    if transport not in _TRANSPORTS:
        raise ConnectorError("invalid_configuration", "stale transport")
    security.enforce_outbound_policy(base_url, environment=environment)
    with safe_http.build_client(environment) as client:
        partner_id = _invoice(client, base_url=base_url, database=database, transport=transport,
                              login=login, secret=secret, company_id=company_id,
                              invoice_id=invoice_id, as_of_date=as_of_date, now=now)
        if partner_id != _positive(expected_partner_id, "expected_partner_id"):
            raise CollectionMessagePolicyError("invoice recipient changed")
        existing = _find(client, base_url=base_url, database=database, transport=transport,
                         login=login, secret=secret, invoice_id=invoice_id, marker=marker,
                         expected_body=body, expected_partner_id=partner_id)
        created = existing is None
        if existing is None:
            kwargs = {
                "body": body,
                "message_type": "comment",
                "subtype_xmlid": "mail.mt_comment",
                "partner_ids": [partner_id],
            }
            if transport == "json2":
                response = json2._post(client, base_url, "account.move", "message_post", secret,
                                       database, {"ids": [invoice_id], **kwargs})
                result = _unwrap(response)
            else:
                uid = legacy_xmlrpc.authenticate(client, base_url, database, login, secret)
                result = legacy_xmlrpc._call(
                    client, base_url, "object", "execute_kw",
                    (database, uid, secret, "account.move", "message_post", [[invoice_id]], kwargs),
                )
            if isinstance(result, list) and len(result) == 1:
                result = result[0]
            if isinstance(result, bool) or not isinstance(result, int) or result < 1:
                raise ConnectorError("unsupported_response", "invalid message receipt")
            existing = result
        verified = _find(client, base_url=base_url, database=database, transport=transport,
                         login=login, secret=secret, invoice_id=invoice_id, marker=marker,
                         expected_body=body, expected_partner_id=partner_id)
        if verified is None or verified != existing:
            raise ConnectorError("unsupported_response", "message was not reconciled")
    return {"message_id": verified, "created": created, "verified": True}
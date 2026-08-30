"""Narrow, idempotent Odoo write operation for invoice activities.

This module deliberately exposes one business operation only: create one
``mail.activity`` linked to one customer invoice.  Model names, method names,
domains, fields, and create values are all owned here; callers cannot dispatch
arbitrary Odoo operations or supply context.
"""

import re
from datetime import date
from typing import Any

import httpx

from . import http as safe_http
from . import json2, legacy_xmlrpc, security
from .errors import ConnectorError

_ALLOWED_TRANSPORTS = ("xmlrpc", "json2")
_MARKER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,63}")
_MAX_SUMMARY_LENGTH = 255
_MAX_RECORD_ID = 2_147_483_647


class ActivityWritePolicyError(Exception):
    """A local policy violation raised before any outbound request."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _positive_id(value: Any, field_name: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > _MAX_RECORD_ID
    ):
        raise ActivityWritePolicyError(f"{field_name} must be a positive integer")
    return value


def _safe_summary(summary: Any, marker: Any) -> tuple[str, str]:
    if not isinstance(marker, str) or _MARKER_RE.fullmatch(marker) is None:
        raise ActivityWritePolicyError("idempotency_marker has invalid format")
    if not isinstance(summary, str) or not summary:
        raise ActivityWritePolicyError("summary is required")
    if any(ord(char) < 32 or ord(char) == 127 for char in summary):
        raise ActivityWritePolicyError("summary contains control characters")
    suffix = f" [Modeem:{marker}]"
    if len(summary) + len(suffix) > _MAX_SUMMARY_LENGTH:
        raise ActivityWritePolicyError("summary is too long")
    return summary + suffix, marker


def _safe_deadline(value: Any) -> str:
    if not isinstance(value, str):
        raise ActivityWritePolicyError("date_deadline must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ActivityWritePolicyError("date_deadline must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise ActivityWritePolicyError("date_deadline must be an ISO date")
    return value


def _unwrap_json_response(response: httpx.Response) -> Any:
    if response.status_code in (301, 302, 303, 307, 308):
        raise ConnectorError("unsupported_response", "redirect")
    if response.status_code == 404:
        raise ConnectorError("json2_unavailable")
    if response.status_code == 401:
        raise ConnectorError("authentication_failed")
    if response.status_code == 403:
        raise ConnectorError("access_denied")
    if response.status_code >= 500:
        raise ConnectorError("server_unreachable")
    if response.status_code != 200:
        raise ConnectorError("unsupported_response", "unexpected status")
    try:
        body = response.json()
    except ValueError as exc:
        raise ConnectorError("unsupported_response", "invalid JSON") from exc
    return body.get("result") if isinstance(body, dict) and "result" in body else body


def _search_read(
    client: httpx.Client,
    *,
    base_url: str,
    database: str | None,
    transport: str,
    login: str,
    secret: str,
    model: str,
    domain: list[list[Any]],
    fields: list[str],
) -> Any:
    """Internal fixed-call plumbing. No model/domain reaches this from a caller."""
    if transport == "json2":
        return json2.search_read(
            client,
            base_url,
            database,
            secret,
            model=model,
            domain=domain,
            fields=fields,
            offset=0,
            limit=2,
            order="id asc",
        )
    return legacy_xmlrpc.search_read(
        client,
        base_url,
        database,
        login,
        secret,
        model=model,
        domain=domain,
        fields=fields,
        offset=0,
        limit=2,
        order="id asc",
    )


def _one_record(raw: Any, *, unavailable_message: str) -> dict[str, Any]:
    if not isinstance(raw, list):
        raise ConnectorError("unsupported_response", "expected record list")
    if not raw:
        raise ActivityWritePolicyError(unavailable_message)
    if len(raw) != 1 or not isinstance(raw[0], dict):
        raise ConnectorError("unsupported_response", "record lookup was not unique")
    record = raw[0]
    _upstream_id(record.get("id"))
    return record


def _upstream_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConnectorError("unsupported_response", "invalid record id")
    return value


def _relation_id(value: Any) -> int:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or isinstance(value[0], bool)
        or not isinstance(value[0], int)
        or value[0] < 1
    ):
        raise ConnectorError("unsupported_response", "invalid relation")
    return value[0]


def _find_activity(
    client: httpx.Client,
    *,
    base_url: str,
    database: str | None,
    transport: str,
    login: str,
    secret: str,
    invoice_id: int,
    model_id: int,
    marker: str,
) -> int | None:
    marker_tag = f"[Modeem:{marker}]"
    raw = _search_read(
        client,
        base_url=base_url,
        database=database,
        transport=transport,
        login=login,
        secret=secret,
        model="mail.activity",
        domain=[
            ["res_model_id", "=", model_id],
            ["res_id", "=", invoice_id],
            ["summary", "ilike", marker_tag],
        ],
        fields=["id", "res_model_id", "res_id", "summary"],
    )
    if not isinstance(raw, list) or len(raw) > 1:
        raise ConnectorError("unsupported_response", "activity reconciliation was not unique")
    if not raw:
        return None
    record = raw[0]
    if not isinstance(record, dict):
        raise ConnectorError("unsupported_response", "invalid activity")
    activity_id = _upstream_id(record.get("id"))
    if (
        _relation_id(record.get("res_model_id")) != model_id
        or record.get("res_id") != invoice_id
        or not isinstance(record.get("summary"), str)
        or marker_tag not in record["summary"]
    ):
        raise ConnectorError("unsupported_response", "activity verification mismatch")
    return activity_id


def _invoice_model_preconditions(
    client: httpx.Client,
    *,
    base_url: str,
    database: str | None,
    transport: str,
    login: str,
    secret: str,
    company_id: int,
    invoice_id: int,
) -> int:
    invoice = _one_record(
        _search_read(
            client,
            base_url=base_url,
            database=database,
            transport=transport,
            login=login,
            secret=secret,
            model="account.move",
            domain=[
                ["id", "=", invoice_id],
                ["company_id", "=", company_id],
                ["move_type", "in", ["out_invoice", "out_refund"]],
            ],
            fields=["id", "company_id", "move_type"],
        ),
        unavailable_message="invoice is unavailable for this company",
    )
    if (
        invoice.get("id") != invoice_id
        or _relation_id(invoice.get("company_id")) != company_id
        or invoice.get("move_type") not in ("out_invoice", "out_refund")
    ):
        raise ConnectorError("unsupported_response", "invoice precondition mismatch")

    model_record = _one_record(
        _search_read(
            client,
            base_url=base_url,
            database=database,
            transport=transport,
            login=login,
            secret=secret,
            model="ir.model",
            domain=[["model", "=", "account.move"]],
            fields=["id", "model"],
        ),
        unavailable_message="account.move model is unavailable",
    )
    if model_record.get("model") != "account.move":
        raise ConnectorError("unsupported_response", "model precondition mismatch")
    return _upstream_id(model_record["id"])


def reconcile_invoice_activity(
    *,
    base_url: str,
    database: str | None,
    transport: str,
    login: str,
    secret: str,
    environment: str,
    company_id: int,
    invoice_id: int,
    summary: str,
    idempotency_marker: str,
) -> dict[str, Any]:
    """Read an activity by the operation's exact server-owned identity.

    This performs the same company/customer-invoice preconditions as create
    and returns no chatter body or other activity data.
    """
    safe_company_id = _positive_id(company_id, "company_id")
    safe_invoice_id = _positive_id(invoice_id, "invoice_id")
    _tagged_summary, safe_marker = _safe_summary(summary, idempotency_marker)
    if transport not in _ALLOWED_TRANSPORTS:
        raise ConnectorError("invalid_configuration", "stale transport")

    security.enforce_outbound_policy(base_url, environment=environment)
    with safe_http.build_client(environment) as client:
        model_id = _invoice_model_preconditions(
            client,
            base_url=base_url,
            database=database,
            transport=transport,
            login=login,
            secret=secret,
            company_id=safe_company_id,
            invoice_id=safe_invoice_id,
        )
        activity_id = _find_activity(
            client,
            base_url=base_url,
            database=database,
            transport=transport,
            login=login,
            secret=secret,
            invoice_id=safe_invoice_id,
            model_id=model_id,
            marker=safe_marker,
        )
    return {
        "operation": "invoice_activity",
        "activity_id": activity_id,
        "invoice_id": safe_invoice_id,
        "found": activity_id is not None,
        "idempotency_marker": safe_marker,
        "transport": transport,
    }


def _create_one_activity(
    client: httpx.Client,
    *,
    base_url: str,
    database: str | None,
    transport: str,
    login: str,
    secret: str,
    values: dict[str, Any],
) -> int:
    if transport == "json2":
        response = json2._post(  # secure bounded HTTP path; endpoint is fixed here
            client,
            base_url,
            "mail.activity",
            "create",
            secret,
            database,
            {"vals_list": [values]},
        )
        raw = _unwrap_json_response(response)
        if isinstance(raw, list) and len(raw) == 1:
            raw = raw[0]
        return _upstream_id(raw)

    uid = legacy_xmlrpc.authenticate(client, base_url, database, login, secret)
    raw = legacy_xmlrpc._call(  # secure bounded HTTP path; operation is fixed here
        client,
        base_url,
        "object",
        "execute_kw",
        (database, uid, secret, "mail.activity", "create", [values]),
    )
    return _upstream_id(raw)


def create_invoice_activity(
    *,
    base_url: str,
    database: str | None,
    transport: str,
    login: str,
    secret: str,
    environment: str,
    company_id: int,
    invoice_id: int,
    activity_type_id: int,
    summary: str,
    date_deadline: str,
    idempotency_marker: str,
) -> dict[str, Any]:
    """Create or reconcile exactly one activity on a customer invoice.

    The deterministic marker is embedded in ``summary`` and used as the
    immutable reconciliation identity before and after creation. A retry
    therefore returns the existing activity even if its human title changed.
    """
    safe_company_id = _positive_id(company_id, "company_id")
    safe_invoice_id = _positive_id(invoice_id, "invoice_id")
    safe_activity_type_id = _positive_id(activity_type_id, "activity_type_id")
    tagged_summary, safe_marker = _safe_summary(summary, idempotency_marker)
    safe_deadline = _safe_deadline(date_deadline)
    if transport not in _ALLOWED_TRANSPORTS:
        raise ConnectorError("invalid_configuration", "stale transport")

    security.enforce_outbound_policy(base_url, environment=environment)
    with safe_http.build_client(environment) as client:
        model_id = _invoice_model_preconditions(
            client,
            base_url=base_url,
            database=database,
            transport=transport,
            login=login,
            secret=secret,
            company_id=safe_company_id,
            invoice_id=safe_invoice_id,
        )

        activity_type = _one_record(
            _search_read(
                client,
                base_url=base_url,
                database=database,
                transport=transport,
                login=login,
                secret=secret,
                model="mail.activity.type",
                domain=[["id", "=", safe_activity_type_id]],
                fields=["id"],
            ),
            unavailable_message="activity type is unavailable",
        )
        if activity_type.get("id") != safe_activity_type_id:
            raise ConnectorError("unsupported_response", "activity type mismatch")

        existing_id = _find_activity(
            client,
            base_url=base_url,
            database=database,
            transport=transport,
            login=login,
            secret=secret,
            invoice_id=safe_invoice_id,
            model_id=model_id,
            marker=safe_marker,
        )
        if existing_id is not None:
            return {
                "operation": "invoice_activity",
                "activity_id": existing_id,
                "invoice_id": safe_invoice_id,
                "created": False,
                "idempotency_marker": safe_marker,
                "transport": transport,
            }

        created_id = _create_one_activity(
            client,
            base_url=base_url,
            database=database,
            transport=transport,
            login=login,
            secret=secret,
            values={
                "activity_type_id": safe_activity_type_id,
                "res_model_id": model_id,
                "res_id": safe_invoice_id,
                "summary": tagged_summary,
                "date_deadline": safe_deadline,
            },
        )
        verified_id = _find_activity(
            client,
            base_url=base_url,
            database=database,
            transport=transport,
            login=login,
            secret=secret,
            invoice_id=safe_invoice_id,
            model_id=model_id,
            marker=safe_marker,
        )
        if verified_id is None or verified_id != created_id:
            raise ConnectorError("unsupported_response", "activity create not reconciled")
        return {
            "operation": "invoice_activity",
            "activity_id": verified_id,
            "invoice_id": safe_invoice_id,
            "created": True,
            "idempotency_marker": safe_marker,
            "transport": transport,
        }
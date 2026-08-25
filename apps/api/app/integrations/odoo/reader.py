"""Generic safe read-page service (Phase 2D).

Single entry point for policy-driven, READ-ONLY Odoo page reads:

1. Resolve the Modeem resource policy (no raw model names from callers).
2. Validate fields / filters / order / pagination against the policy —
   any violation raises ReadPolicyError BEFORE any network activity.
3. Convert safe AND-only filters into an Odoo domain internally.
4. Dispatch to the transport selected by the last SUCCESSFUL connection
   test (no version rediscovery, no silent transport switching).
5. Sanitize the upstream response: only requested/allowlisted fields
   survive; malformed shapes map to safe `unsupported_response`.

No write/create/unlink operation exists anywhere in this module, and no
Odoo record is persisted locally.
"""

import re
from typing import Any

from . import http as safe_http
from . import json2, legacy_xmlrpc, security
from .errors import ConnectorError
from .read_policies import (
    MAX_FILTER_LIST_ITEMS,
    MAX_FILTER_STRING_LENGTH,
    MAX_FILTERS,
    MAX_PREVIEW_OFFSET,
    MAX_REQUESTED_FIELDS,
    ReadFieldPolicy,
    ReadPolicy,
    get_policy,
)

_ALLOWED_TRANSPORTS = ("xmlrpc", "json2")


class ReadPolicyError(Exception):
    """A Modeem-side policy violation. Raised BEFORE any network call and
    never forwarded to Odoo. `message` contains only static safe text."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _validate_fields(policy: ReadPolicy, fields: list[str] | None) -> list[str]:
    if fields is None:
        return list(policy.default_fields)
    if len(fields) > MAX_REQUESTED_FIELDS:
        raise ReadPolicyError("too many fields requested")
    normalized: list[str] = []
    for name in fields:
        if not isinstance(name, str) or name not in policy.allowed_fields:
            raise ReadPolicyError("field not allowed for this resource")
        if name not in normalized:  # normalize duplicates safely
            normalized.append(name)
    if not normalized:
        raise ReadPolicyError("at least one field required")
    return normalized

def _validate_typed_scalar(field_policy: ReadFieldPolicy, value: Any) -> Any:
    """Strict type check against the server-side field policy. NO coercion:
    "123" is never accepted for an integer field, and bool never counts as
    an integer/number. Integer fields also enforce the declared range and
    string fields the declared fullmatch pattern."""
    kind = field_policy.value_type
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ReadPolicyError("filter value type mismatch")
        if value < field_policy.min_value or value > field_policy.max_value:
            raise ReadPolicyError("filter value out of range")
        return value
    if kind == "string":
        if not isinstance(value, str):
            raise ReadPolicyError("filter value type mismatch")
        if len(value) > MAX_FILTER_STRING_LENGTH:
            raise ReadPolicyError("filter value too long")
        if field_policy.max_length is not None and len(value) > field_policy.max_length:
            raise ReadPolicyError("filter value too long")
        if (
            field_policy.pattern is not None
            and re.fullmatch(field_policy.pattern, value) is None
        ):
            raise ReadPolicyError("filter value has invalid format")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ReadPolicyError("filter value type mismatch")
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ReadPolicyError("filter value type mismatch")
        return value
    raise ReadPolicyError("unsupported filter value type")


def _validate_filters(
    policy: ReadPolicy, filters: list[dict[str, Any]] | None
) -> list[list[Any]]:
    """Convert validated AND-only filters into an Odoo domain. Raw domain
    syntax (|, &, !, nested lists) is structurally impossible: only
    {field, operator, value} objects are accepted."""
    if not filters:
        return []
    if len(filters) > MAX_FILTERS:
        raise ReadPolicyError("too many filters")
    domain: list[list[Any]] = []
    for item in filters:
        fld = item.get("field")
        op = item.get("operator")
        value = item.get("value")
        if not isinstance(fld, str) or fld not in policy.allowed_filter_fields:
            raise ReadPolicyError("filter field not allowed")
        if not isinstance(op, str) or op not in policy.allowed_filter_operators:
            raise ReadPolicyError("filter operator not allowed")
        field_policy = policy.fields.get(fld)
        if field_policy is None:
            raise ReadPolicyError("filter field not allowed")
        if op == "in":
            if not isinstance(value, list) or not value:
                raise ReadPolicyError("'in' filter requires a non-empty list")
            if len(value) > MAX_FILTER_LIST_ITEMS:
                raise ReadPolicyError("filter list too long")
            # Every item must match the field type; mixed lists rejected.
            value = [_validate_typed_scalar(field_policy, v) for v in value]
        elif op == "ilike":
            if field_policy.value_type != "string":
                raise ReadPolicyError("'ilike' is only valid for string fields")
            if not isinstance(value, str):
                raise ReadPolicyError("'ilike' filter requires a string")
            _validate_typed_scalar(field_policy, value)
        else:
            value = _validate_typed_scalar(field_policy, value)
        domain.append([fld, op, value])
    return domain


def _validate_order(
    policy: ReadPolicy, order_by: str | None, order_direction: str
) -> str | None:
    if order_by is None:
        return None
    if order_by not in policy.allowed_order_fields:
        raise ReadPolicyError("order field not allowed")
    if order_direction not in ("asc", "desc"):
        raise ReadPolicyError("order direction must be asc or desc")
    return f"{order_by} {order_direction}"


def _validate_pagination(policy: ReadPolicy, limit: int, offset: int) -> None:
    if not isinstance(limit, int) or limit < 1 or limit > policy.max_page_size:
        raise ReadPolicyError("limit out of range")
    if not isinstance(offset, int) or offset < 0 or offset > MAX_PREVIEW_OFFSET:
        raise ReadPolicyError("offset out of range")


def _check_output_value(field_policy: ReadFieldPolicy, value: Any) -> None:
    """Strict output-type validation per the server-side field policy.
    NO silent coercion of attacker-controlled upstream values; a mismatch
    raises safe unsupported_response with NO raw value in the detail."""
    if value is None:
        if field_policy.nullable:
            return
        raise ConnectorError("unsupported_response", "null field value")
    kind = field_policy.value_type
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConnectorError("unsupported_response", "field type mismatch")
    elif kind == "string":
        if not isinstance(value, str):
            raise ConnectorError("unsupported_response", "field type mismatch")
        if field_policy.max_length is not None and len(value) > field_policy.max_length:
            raise ConnectorError("unsupported_response", "field value too long")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ConnectorError("unsupported_response", "field type mismatch")
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConnectorError("unsupported_response", "field type mismatch")
    else:  # pragma: no cover - registry only defines the four types
        raise ConnectorError("unsupported_response", "unknown field type")


def _sanitize_records(
    raw: Any, policy: ReadPolicy, fields: list[str], max_expected: int
) -> list[dict[str, Any]]:
    """Never blindly return the upstream response: enforce shape, bounds,
    field allowlisting, AND per-field value types. Extra upstream fields
    are DROPPED."""
    if not isinstance(raw, list):
        raise ConnectorError("unsupported_response", "not a list")
    if len(raw) > max_expected:
        raise ConnectorError("unsupported_response", "too many records returned")
    sanitized: list[dict[str, Any]] = []
    for record in raw:
        if not isinstance(record, dict):
            raise ConnectorError("unsupported_response", "record not an object")
        if "id" in record and (
            isinstance(record["id"], bool)
            or not isinstance(record["id"], int)
            or record["id"] <= 0
        ):
            raise ConnectorError("unsupported_response", "invalid record id")
        clean: dict[str, Any] = {}
        for k in fields:
            if k not in record:
                continue
            _check_output_value(policy.fields[k], record[k])
            clean[k] = record[k]
        sanitized.append(clean)
    return sanitized


def read_page(
    *,
    base_url: str,
    database: str | None,
    transport: str,
    login: str,
    secret: str,
    environment: str,
    resource: str,
    fields: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    limit: int,
    offset: int,
    order_by: str | None = None,
    order_direction: str = "asc",
) -> dict[str, Any]:
    """Read exactly ONE bounded page. Raises ReadPolicyError for Modeem-side
    violations (before any network call) and ConnectorError for safe
    upstream failures. Never loops through the dataset and never calls
    search_count."""
    policy = get_policy(resource)
    if policy is None:
        raise ReadPolicyError("unknown resource")
    safe_fields = _validate_fields(policy, fields)
    domain = _validate_filters(policy, filters)
    safe_order = _validate_order(policy, order_by, order_direction)
    _validate_pagination(policy, limit, offset)
    if transport not in _ALLOWED_TRANSPORTS:
        raise ConnectorError("invalid_configuration", "stale transport")

    # Defense-in-depth; the client hook revalidates before every request.
    security.enforce_outbound_policy(base_url, environment=environment)

    upstream_limit = limit + 1  # one extra record only, to compute has_more
    with safe_http.build_client(environment) as client:
        if transport == "json2":
            raw = json2.search_read(
                client,
                base_url,
                database,
                secret,
                model=policy.odoo_model,
                domain=domain,
                fields=safe_fields,
                offset=offset,
                limit=upstream_limit,
                order=safe_order,
            )
        else:
            raw = legacy_xmlrpc.search_read(
                client,
                base_url,
                database,
                login,
                secret,
                model=policy.odoo_model,
                domain=domain,
                fields=safe_fields,
                offset=offset,
                limit=upstream_limit,
                order=safe_order,
            )

    records = _sanitize_records(raw, policy, safe_fields, max_expected=upstream_limit)
    has_more = len(records) > limit
    records = records[:limit]
    return {
        "resource": policy.resource_key,
        "fields": safe_fields,
        "records": records,
        "limit": limit,
        "offset": offset,
        "returned_count": len(records),
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
        "transport": transport,
    }

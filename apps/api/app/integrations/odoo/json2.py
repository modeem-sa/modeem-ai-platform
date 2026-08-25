"""Odoo 19+ JSON-2 adapter — used ONLY when auth_mode is explicitly api_key.

Endpoint format: /json/2/<model>/<method>
Auth: `Authorization: bearer <API_KEY>`; `X-Odoo-Database` when configured.

The probe is a harmless zero-result search_count using a domain that can
never match a record ([["id", "=", 0]]). It proves the JSON-2 endpoint
exists, the API key is accepted, database selection works, and Odoo
access-right validation runs — WITHOUT returning any business record.
"""

from typing import Any

import httpx

from .errors import ConnectorError
from .http import post_limited

transport = "json2"


def _headers(api_key: str, database: str | None) -> dict[str, str]:
    headers = {"Authorization": f"bearer {api_key}", "Content-Type": "application/json"}
    if database:
        headers["X-Odoo-Database"] = database
    return headers


def _post(
    client: httpx.Client,
    base_url: str,
    model: str,
    method: str,
    api_key: str,
    database: str | None,
    payload: dict[str, Any],
) -> httpx.Response:
    url = f"{base_url}/json/2/{model}/{method}"
    try:
        return post_limited(client, url, json=payload, headers=_headers(api_key, database))
    except (httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
        raise ConnectorError("connection_timeout") from exc
    except httpx.ConnectError as exc:
        text = str(exc).lower()
        if "certificate" in text or "ssl" in text or "tls" in text:
            raise ConnectorError("tls_error") from exc
        raise ConnectorError("server_unreachable") from exc
    except httpx.HTTPError as exc:
        raise ConnectorError("server_unreachable") from exc


def probe_auth(
    client: httpx.Client, base_url: str, database: str | None, api_key: str
) -> None:
    """Zero-result search_count probe; raises ConnectorError on failure."""
    response = _post(
        client,
        base_url,
        "res.users",
        "search_count",
        api_key,
        database,
        {"domain": [["id", "=", 0]]},
    )
    if response.status_code in (301, 302, 303, 307, 308):
        raise ConnectorError("unsupported_response", "redirect")
    if response.status_code == 404:
        raise ConnectorError("json2_unavailable")
    if response.status_code in (401, 403):
        raise ConnectorError("authentication_failed")
    if response.status_code >= 500:
        raise ConnectorError("server_unreachable")
    if response.status_code != 200:
        raise ConnectorError("unsupported_response", f"status {response.status_code}")
    try:
        body = response.json()
    except ValueError as exc:
        raise ConnectorError("unsupported_response") from exc
    # A search_count over an impossible domain must be an integer 0.
    if body not in (0, {"result": 0}):
        raise ConnectorError("unsupported_response")


def search_read(
    client: httpx.Client,
    base_url: str,
    database: str | None,
    api_key: str,
    *,
    model: str,
    domain: list,
    fields: list[str],
    offset: int,
    limit: int,
    order: str | None,
) -> Any:
    """READ-ONLY search_read over JSON-2. `model`, `fields`, and `order`
    come exclusively from the server-side read policy. Body contains only
    validated named arguments — no user-provided context."""
    payload: dict[str, Any] = {
        "domain": domain,
        "fields": list(fields),
        "offset": offset,
        "limit": limit,
    }
    if order:
        payload["order"] = order
    response = _post(client, base_url, model, "search_read", api_key, database, payload)
    if response.status_code in (301, 302, 303, 307, 308):
        raise ConnectorError("unsupported_response", "redirect")
    if response.status_code == 404:
        raise ConnectorError("json2_unavailable")
    if response.status_code == 401:
        raise ConnectorError("authentication_failed")
    if response.status_code == 403:
        # Authenticated but lacking permission. Error body never leaks.
        raise ConnectorError("access_denied")
    if response.status_code >= 500:
        raise ConnectorError("server_unreachable")
    if response.status_code != 200:
        raise ConnectorError("unsupported_response", f"status {response.status_code}")
    try:
        body = response.json()
    except ValueError as exc:
        raise ConnectorError("unsupported_response") from exc
    if isinstance(body, dict) and isinstance(body.get("result"), list):
        return body["result"]
    return body


def detect_edition(
    client: httpx.Client, base_url: str, database: str | None, api_key: str
) -> tuple[str, str]:
    """Best-effort technical module check over JSON-2; never fails the test."""
    try:
        response = _post(
            client,
            base_url,
            "ir.module.module",
            "search_count",
            api_key,
            database,
            {"domain": [["name", "=", "web_enterprise"], ["state", "=", "installed"]]},
        )
    except ConnectorError:
        return "unknown", "module_check_denied_or_failed"
    if response.status_code != 200:
        return "unknown", "module_check_denied_or_failed"
    try:
        body = response.json()
    except ValueError:
        return "unknown", "module_check_inconclusive"
    count = body.get("result") if isinstance(body, dict) else body
    if isinstance(count, int):
        if count > 0:
            return "enterprise", "web_enterprise_installed"
        return "community", "web_enterprise_absent"
    return "unknown", "module_check_inconclusive"

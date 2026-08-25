"""Legacy Odoo XML-RPC adapter (Odoo 16/18 and compatibility mode for 19+).

XML encoding/decoding uses the standard-library `xmlrpc.client` marshalling
ONLY — the actual HTTP request always goes through the centralized secure
httpx client, so URL validation, DNS policy, redirect policy, timeouts, and
TLS verification are never bypassed by an uncontrolled ServerProxy transport.

API keys on legacy Odoo versions are passed in the same credential position
as the password, per Odoo's external API contract.
"""

import xmlrpc.client
from typing import Any

import httpx

from .errors import ConnectorError
from .http import post_limited
from .schemas import OdooVersionInfo

transport = "xmlrpc"

_XML_HEADERS = {"Content-Type": "text/xml"}


def _call(
    client: httpx.Client, base_url: str, endpoint: str, method: str, params: tuple
) -> Any:
    """Marshal an XML-RPC call and send it through the secure client."""
    payload = xmlrpc.client.dumps(params, methodname=method, allow_none=False)
    url = f"{base_url}/xmlrpc/2/{endpoint}"
    try:
        response = post_limited(client, url, content=payload.encode("utf-8"), headers=_XML_HEADERS)
    except httpx.ConnectTimeout as exc:
        raise ConnectorError("connection_timeout") from exc
    except httpx.ReadTimeout as exc:
        raise ConnectorError("connection_timeout") from exc
    except httpx.ConnectError as exc:
        # TLS problems surface as ConnectError with certificate details.
        text = str(exc).lower()
        if "certificate" in text or "ssl" in text or "tls" in text:
            raise ConnectorError("tls_error") from exc
        raise ConnectorError("server_unreachable") from exc
    except httpx.HTTPError as exc:
        raise ConnectorError("server_unreachable") from exc
    if response.status_code >= 500:
        raise ConnectorError("server_unreachable", f"status {response.status_code}")
    if response.status_code in (301, 302, 303, 307, 308):
        # Redirects are never followed.
        raise ConnectorError("unsupported_response", "redirect")
    if response.status_code != 200:
        raise ConnectorError("not_odoo", f"status {response.status_code}")
    try:
        result, _ = xmlrpc.client.loads(response.text)
    except xmlrpc.client.Fault as fault:
        raise _map_fault(fault) from fault
    except Exception as exc:  # malformed / non-XML-RPC body
        raise ConnectorError("not_odoo") from exc
    return result[0] if result else None


def _map_fault(fault: xmlrpc.client.Fault) -> ConnectorError:
    text = (fault.faultString or "").lower()
    if "database" in text and ("not exist" in text or "not found" in text):
        return ConnectorError("database_not_found")
    if "access denied" in text or "accessdenied" in text:
        return ConnectorError("authentication_failed")
    if (
        "accesserror" in text
        or "not allowed" in text
        or "access right" in text
        or "access rights" in text
    ):
        # Authenticated but lacking model permission. Raw text never leaks.
        return ConnectorError("access_denied")
    # Never propagate the raw fault string to callers/API.
    return ConnectorError("unsupported_response")


def probe_version(client: httpx.Client, base_url: str) -> OdooVersionInfo:
    """Unauthenticated common.version() metadata call."""
    raw = _call(client, base_url, "common", "version", ())
    if not isinstance(raw, dict):
        raise ConnectorError("not_odoo")
    server_version = raw.get("server_version")
    version_info = raw.get("server_version_info")
    if not isinstance(server_version, str) or not isinstance(version_info, (list, tuple)):
        raise ConnectorError("unsupported_response")
    if not version_info or not isinstance(version_info[0], int) or version_info[0] <= 0:
        raise ConnectorError("unsupported_response")
    serie = raw.get("server_serie")
    protocol = raw.get("protocol_version")
    return OdooVersionInfo(
        server_version=server_version,
        major=int(version_info[0]),
        server_serie=serie if isinstance(serie, str) else None,
        protocol_version=protocol if isinstance(protocol, int) else None,
    )


def authenticate(
    client: httpx.Client,
    base_url: str,
    database: str | None,
    login: str,
    secret: str,
) -> int:
    """authenticate(db, login, password_or_api_key, {}) — returns uid."""
    if not database:
        raise ConnectorError("invalid_configuration", "database_name required")
    uid = _call(
        client, base_url, "common", "authenticate", (database, login, secret, {})
    )
    if not isinstance(uid, int) or uid <= 0:
        raise ConnectorError("authentication_failed")
    return uid


def probe_capabilities(
    client: httpx.Client,
    base_url: str,
    database: str | None,
    login: str,
    secret: str,
    version: OdooVersionInfo,
) -> dict[str, Any]:
    return {"legacy_xmlrpc": True}


def search_read(
    client: httpx.Client,
    base_url: str,
    database: str | None,
    login: str,
    secret: str,
    *,
    model: str,
    domain: list,
    fields: list[str],
    offset: int,
    limit: int,
    order: str | None,
) -> Any:
    """READ-ONLY search_read via execute_kw. `model`, `fields`, and `order`
    come exclusively from the server-side read policy — no caller controls
    them, and no other method name is ever sent."""
    uid = authenticate(client, base_url, database, login, secret)
    kwargs: dict[str, Any] = {
        "fields": list(fields),
        "offset": offset,
        "limit": limit,
    }
    if order:
        kwargs["order"] = order
    return _call(
        client,
        base_url,
        "object",
        "execute_kw",
        (database, uid, secret, model, "search_read", [domain], kwargs),
    )


def detect_edition(
    client: httpx.Client,
    base_url: str,
    database: str,
    uid: int,
    secret: str,
) -> tuple[str, str]:
    """Best-effort edition detection via a technical module metadata check.

    Returns (edition, how). NEVER raises past this function — inconclusive
    or denied results map to "unknown". No business records are read.
    """
    try:
        count = _call(
            client,
            base_url,
            "object",
            "execute_kw",
            (
                database,
                uid,
                secret,
                "ir.module.module",
                "search_count",
                [[["name", "=", "web_enterprise"], ["state", "=", "installed"]]],
            ),
        )
    except ConnectorError:
        return "unknown", "module_check_denied_or_failed"
    if isinstance(count, int):
        if count > 0:
            return "enterprise", "web_enterprise_installed"
        return "community", "web_enterprise_absent"
    return "unknown", "module_check_inconclusive"

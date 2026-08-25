"""Centralized Odoo connectivity test orchestration (Phase 2C).

All transport selection lives here — API routes contain no version- or
edition-specific branching.

Transport selection rules:
- auth_mode auto / password  -> legacy XML-RPC (never guess an unknown
  secret is an API key; never send a password as a JSON-2 bearer token)
- auth_mode api_key:
    - detected major >= 19 -> prefer JSON-2; if the JSON-2 endpoint is
      unavailable, fall back to legacy XML-RPC with the API key in the
      password position and report the fallback explicitly
    - detected major < 19  -> legacy XML-RPC with the API key in the
      password position

Unknown Odoo majors are handled by capabilities, not rejected outright.

NO business data is read anywhere in this module.
"""

from typing import Any

from . import http as safe_http
from . import json2, legacy_xmlrpc, security
from .errors import ConnectorError
from .schemas import TestOutcome


def test_connection(
    *,
    base_url: str,
    database: str | None,
    auth_mode: str,
    login: str,
    secret: str,
    environment: str,
) -> TestOutcome:
    """Run the full technical connectivity test. Never raises: every failure
    is a TestOutcome with a safe normalized error code."""
    try:
        return _run(
            base_url=base_url,
            database=database,
            auth_mode=auth_mode,
            login=login,
            secret=secret,
            environment=environment,
        )
    except ConnectorError as exc:
        return TestOutcome(success=False, error_code=exc.code)
    except Exception:  # noqa: BLE001 — deliberate: no library detail may leak
        # Absolutely no library exception detail may leak upward.
        return TestOutcome(success=False, error_code="internal_connector_error")


def _run(
    *,
    base_url: str,
    database: str | None,
    auth_mode: str,
    login: str,
    secret: str,
    environment: str,
) -> TestOutcome:
    # Connector-level outbound policy check (defense-in-depth). The client
    # itself revalidates DNS/IP before EVERY request via its request hook.
    security.enforce_outbound_policy(base_url, environment=environment)

    capabilities: dict[str, Any] = {}
    with safe_http.build_client(environment) as client:
        version = legacy_xmlrpc.probe_version(client, base_url)
        capabilities["legacy_xmlrpc"] = True
        capabilities["server_serie"] = version.server_serie
        if version.major not in (16, 18, 19):
            # Not an immediate rejection: record and continue via
            # compatibility XML-RPC capabilities.
            capabilities["version_support"] = "best_effort"

        transport = "xmlrpc"
        edition = "unknown"
        edition_how = "not_attempted"

        if auth_mode == "api_key" and version.major >= 19:
            # Prefer JSON-2 for explicit API keys on modern servers.
            try:
                json2.probe_auth(client, base_url, database, secret)
                capabilities["json2"] = True
                transport = "json2"
            except ConnectorError as exc:
                if exc.code == "json2_unavailable":
                    # Explicit, reported fallback to legacy XML-RPC.
                    capabilities["json2"] = False
                    capabilities["json2_fallback"] = "legacy_xmlrpc"
                else:
                    raise
        if transport == "json2":
            edition, edition_how = json2.detect_edition(
                client, base_url, database, secret
            )
        else:
            # auto/password, api_key on <19, or explicit JSON-2 fallback:
            # legacy XML-RPC authentication (API key in password position).
            uid = legacy_xmlrpc.authenticate(client, base_url, database, login, secret)
            capabilities.update(
                legacy_xmlrpc.probe_capabilities(
                    client, base_url, database, login, secret, version
                )
            )
            if database:
                edition, edition_how = legacy_xmlrpc.detect_edition(
                    client, base_url, database, uid, secret
                )
        capabilities["edition_detection"] = edition_how

    return TestOutcome(
        success=True,
        odoo_version=version.server_version,
        odoo_major=version.major,
        edition=edition,
        transport=transport,
        capabilities=capabilities,
    )

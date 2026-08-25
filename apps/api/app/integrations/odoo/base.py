"""Common adapter interface for Odoo transports (Phase 2C).

Adapters implement technical connectivity only — version probing,
authentication verification, and harmless capability probes. No adapter
may read, create, update, or delete business records.

Transport selection is centralized in `connector.py`; API routes must not
contain version-specific branching.
"""

from typing import Any, Protocol

import httpx

from .schemas import OdooVersionInfo


class OdooAdapter(Protocol):
    """Protocol for Odoo transport adapters."""

    transport: str  # "xmlrpc" | "json2"

    def authenticate(
        self,
        client: httpx.Client,
        base_url: str,
        database: str | None,
        login: str,
        secret: str,
    ) -> Any:
        """Verify credentials. Raises ConnectorError on failure."""
        ...

    def probe_capabilities(
        self,
        client: httpx.Client,
        base_url: str,
        database: str | None,
        login: str,
        secret: str,
        version: OdooVersionInfo,
    ) -> dict[str, Any]:
        """Harmless technical capability probe — never business records."""
        ...

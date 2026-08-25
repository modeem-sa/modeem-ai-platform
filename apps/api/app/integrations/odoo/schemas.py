"""Internal dataclasses for the Odoo connector (Phase 2C).

These are backend-internal; the API layer maps them to safe responses.
Credentials never appear in any of these structures.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OdooVersionInfo:
    server_version: str  # e.g. "18.0"
    major: int  # e.g. 18
    server_serie: str | None = None
    protocol_version: int | None = None


@dataclass
class TestOutcome:
    success: bool
    error_code: str | None = None
    odoo_version: str | None = None
    odoo_major: int | None = None
    edition: str = "unknown"  # community | enterprise | unknown
    transport: str = "unknown"  # xmlrpc | json2 | unknown
    capabilities: dict[str, Any] = field(default_factory=dict)
